#!/usr/bin/env python3
"""Radar-relative rolling 3D cloud visualization (not a global SLAM map)."""

import math
import threading
from collections import deque

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Header
from std_srvs.srv import Empty, EmptyResponse, SetBool, SetBoolResponse


PREFERRED_FIELDS = ("x", "y", "z", "doppler", "snr", "noise")


def valid_parameters(min_range, max_range, min_elevation, max_elevation,
                     voxel_size, max_points, history_sec, publish_rate):
    return (0.0 <= min_range < max_range and
            min_elevation <= max_elevation and voxel_size > 0.0 and
            max_points > 0 and history_sec > 0.0 and publish_rate > 0.0)


def filter_point_dicts(points, min_range, max_range, min_elevation,
                       max_elevation, min_snr, horizontal_epsilon=1e-6):
    """Filter dictionaries in original radar XYZ coordinates; bounds inclusive."""
    accepted = []
    for point in points:
        try:
            x, y, z = float(point["x"]), float(point["y"]), float(point["z"])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (x, y, z)):
            continue
        horizontal = math.hypot(x, y)
        if horizontal <= horizontal_epsilon:
            continue
        distance = math.sqrt(x * x + y * y + z * z)
        elevation = math.degrees(math.atan2(z, horizontal))
        snr = point.get("snr")
        if snr is not None and (not math.isfinite(float(snr)) or float(snr) < min_snr):
            continue
        # PointCloud2 FLOAT32 quantization shifts exact angle boundaries by
        # roughly 1e-7 degrees, so retain a small numerical tolerance.
        boundary_tolerance = 1e-5
        if (min_range - boundary_tolerance <= distance <= max_range + boundary_tolerance and
                min_elevation - boundary_tolerance <= elevation <=
                max_elevation + boundary_tolerance):
            accepted.append(dict(point))
    return accepted


def voxel_downsample(points, voxel_size):
    """Keep the newest point per voxel; input order is oldest to newest."""
    voxels = {}
    for point in points:
        key = (math.floor(point["x"] / voxel_size),
               math.floor(point["y"] / voxel_size),
               math.floor(point["z"] / voxel_size))
        voxels[key] = point
    return sorted(voxels.values(), key=lambda point: point["_order"])


def quaternion_rotate_translate(point, transform):
    """Apply geometry_msgs/Transform without adding a tf2_sensor_msgs dependency."""
    q = transform.rotation
    tx, ty, tz = transform.translation.x, transform.translation.y, transform.translation.z
    x, y, z = point["x"], point["y"], point["z"]
    # Quaternion-vector rotation using t=2*(q.xyz cross v).
    ux, uy, uz = q.x, q.y, q.z
    cross_x = uy * z - uz * y
    cross_y = uz * x - ux * z
    cross_z = ux * y - uy * x
    t_x, t_y, t_z = 2.0 * cross_x, 2.0 * cross_y, 2.0 * cross_z
    point = dict(point)
    point["x"] = x + q.w * t_x + (uy * t_z - uz * t_y) + tx
    point["y"] = y + q.w * t_y + (uz * t_x - ux * t_z) + ty
    point["z"] = z + q.w * t_z + (ux * t_y - uy * t_x) + tz
    return point


def output_fields(field_names):
    names = [name for name in PREFERRED_FIELDS if name in field_names]
    return names, [PointField(name=name, offset=index * 4,
                              datatype=PointField.FLOAT32, count=1)
                   for index, name in enumerate(names)]


class Radar3DRollingMap:
    def __init__(self):
        self.min_range = float(rospy.get_param("~min_range_m", 0.2))
        self.max_range = float(rospy.get_param("~max_range_m", 3.0))
        self.min_elevation = float(rospy.get_param("~min_elevation_deg", -10.0))
        self.max_elevation = float(rospy.get_param("~max_elevation_deg", 60.0))
        self.min_snr = float(rospy.get_param("~min_snr_db", 15.0))
        self.history_sec = float(rospy.get_param("~history_sec", 4.0))
        self.voxel_size = float(rospy.get_param("~voxel_size_m", 0.05))
        self.max_points = int(rospy.get_param("~max_points", 50000))
        self.publish_rate = float(rospy.get_param("~publish_rate_hz", 10.0))
        self.output_frame = str(rospy.get_param("~output_frame", "radar_link"))
        if not valid_parameters(
                self.min_range, self.max_range, self.min_elevation,
                self.max_elevation, self.voxel_size, self.max_points,
                self.history_sec, self.publish_rate):
            raise ValueError("invalid rolling-map filter/history parameters")

        self.frames = deque()
        self.lock = threading.RLock()
        self.paused = False
        self.sequence = 0
        self.last_field_names = ("x", "y", "z")
        self.last_source_frame = self.output_frame
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.filtered_pub = rospy.Publisher(
            "/radar/points_3d_filtered", PointCloud2, queue_size=10)
        self.rolling_pub = rospy.Publisher(
            "/radar/rolling_map_3d", PointCloud2, queue_size=10)
        self.subscriber = rospy.Subscriber(
            "/radar/points", PointCloud2, self.cloud_callback, queue_size=20)
        self.clear_service = rospy.Service(
            "/radar/clear_rolling_map_3d", Empty, self.clear_callback)
        self.pause_service = rospy.Service(
            "/radar/pause_rolling_map_3d", SetBool, self.pause_callback)
        self.timer = rospy.Timer(rospy.Duration(1.0 / self.publish_rate), self.timer_callback)
        rospy.loginfo(
            "3D rolling local map: range=%g..%g m elevation=%g..%g deg "
            "snr>=%g history=%g s voxel=%g m max_points=%d frame=%s",
            self.min_range, self.max_range, self.min_elevation,
            self.max_elevation, self.min_snr, self.history_sec,
            self.voxel_size, self.max_points, self.output_frame)

    def dictionaries_from_cloud(self, message):
        available = {field.name for field in message.fields}
        if not {"x", "y", "z"}.issubset(available):
            rospy.logwarn_throttle(5.0, "PointCloud2 has no complete x/y/z fields")
            return [], ("x", "y", "z")
        names = tuple(name for name in PREFERRED_FIELDS if name in available)
        rows = pc2.read_points(message, field_names=names, skip_nans=False)
        return [dict(zip(names, row)) for row in rows], names

    def transform_points(self, points, source_frame, stamp):
        target = self.output_frame or source_frame
        if not source_frame or target == source_frame:
            return points, source_frame or target
        try:
            transform = self.tf_buffer.lookup_transform(
                target, source_frame, stamp, rospy.Duration(0.1)).transform
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as exc:
            rospy.logwarn_throttle(2.0, "3D rolling map TF unavailable: %s", exc)
            return None, target
        return [quaternion_rotate_translate(point, transform) for point in points], target

    def make_cloud(self, points, field_names, frame_id, stamp):
        names, fields = output_fields(field_names)
        header = Header(stamp=stamp, frame_id=frame_id)
        rows = [[point.get(name, float("nan")) for name in names] for point in points]
        return pc2.create_cloud(header, fields, rows)

    def cloud_callback(self, message):
        with self.lock:
            if self.paused:
                return
        raw_points, field_names = self.dictionaries_from_cloud(message)
        filtered = filter_point_dicts(
            raw_points, self.min_range, self.max_range, self.min_elevation,
            self.max_elevation, self.min_snr)
        transformed, frame_id = self.transform_points(
            filtered, message.header.frame_id, message.header.stamp)
        if transformed is None:
            return
        stamp = message.header.stamp if message.header.stamp != rospy.Time() else rospy.Time.now()
        self.filtered_pub.publish(self.make_cloud(transformed, field_names, frame_id, stamp))
        with self.lock:
            if self.paused:
                return
            self.sequence += 1
            for index, point in enumerate(transformed):
                point["_order"] = (stamp.to_sec(), self.sequence, index)
            self.frames.append((stamp.to_sec(), transformed))
            self.last_field_names = field_names
            self.last_source_frame = frame_id

    def prune_locked(self, now_sec):
        while self.frames and now_sec - self.frames[0][0] >= self.history_sec:
            self.frames.popleft()

    def combined_locked(self):
        points = [point for _stamp, frame in self.frames for point in frame]
        points = voxel_downsample(points, self.voxel_size)
        if len(points) > self.max_points:
            points = points[-self.max_points:]
        return points

    def timer_callback(self, _event):
        now = rospy.Time.now()
        with self.lock:
            if not self.paused:
                self.prune_locked(now.to_sec())
            points = self.combined_locked()
            names = self.last_field_names
            frame_id = self.last_source_frame or self.output_frame
        self.rolling_pub.publish(self.make_cloud(points, names, frame_id, now))

    def clear_callback(self, _request):
        with self.lock:
            self.frames.clear()
        return EmptyResponse()

    def pause_callback(self, request):
        with self.lock:
            self.paused = bool(request.data)
        state = "paused" if request.data else "resumed"
        return SetBoolResponse(success=True, message="3D rolling map {}".format(state))


def main():
    rospy.init_node("radar_3d_rolling_map")
    Radar3DRollingMap()
    rospy.spin()


if __name__ == "__main__":
    main()
