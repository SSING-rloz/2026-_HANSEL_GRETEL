#!/usr/bin/env python3
"""Cluster sparse radar returns and estimate obstacle outlines and traversable gaps."""

from collections import deque
import math

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from geometry_msgs.msg import Point
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Float32, Header
from visualization_msgs.msg import Marker, MarkerArray

from iwrl6432_ros.manual_pose_mapping import rotate_translate_3d
from iwrl6432_ros.obstacle_contour import (
    StableClusterIds, describe_cluster, euclidean_clusters, traversable_xy_gaps,
    valid_point, voxel_downsample, xy_gaps,
)


PREFERRED_FIELDS = ("x", "y", "z", "doppler", "snr", "noise")


class RadarObstacleContour:
    def __init__(self):
        gp = rospy.get_param
        self.frame_id = str(gp("~frame_id", "base_link"))
        self.valid_min_range = float(gp("~valid_min_range_m", 0.10))
        self.max_range = float(gp("~max_range_m", 1.0))
        self.min_z, self.max_z = float(gp("~min_z_m", -0.10)), float(gp("~max_z_m", 0.60))
        self.min_snr = float(gp("~min_snr_db", 8.0))
        self.history_frames = int(gp("~history_frames", 8))
        self.history_duration = float(gp("~history_duration_sec", 1.5))
        self.voxel_size = float(gp("~voxel_size_m", 0.02))
        self.max_accumulated_points = int(gp("~max_accumulated_points", 3000))
        self.half_fov = float(gp("~front_fov_deg", 120.0)) * 0.5
        self.cluster_eps = float(gp("~cluster_eps_m", 0.15))
        self.cluster_min_points = int(gp("~cluster_min_points", 2))
        self.max_clusters = int(gp("~max_clusters", 12))
        self.robot_width = float(gp("~robot_width_m", 0.35))
        self.safety_margin = float(gp("~safety_margin_m", 0.025))
        self.min_gap_width = float(gp("~min_gap_width_m", 0.40))
        self.max_gap_depth_offset = float(gp("~max_gap_depth_offset_m", 0.25))
        if not (0 < self.valid_min_range < self.max_range and
                self.min_z <= self.max_z and self.max_accumulated_points > 0 and
                self.history_frames > 0 and self.history_duration > 0 and self.voxel_size > 0 and
                0 < self.half_fov <= 90 and self.cluster_eps > 0 and
                self.cluster_min_points > 0 and self.max_gap_depth_offset > 0 and
                self.robot_width > 0 and self.safety_margin >= 0 and self.min_gap_width > 0):
            raise ValueError("invalid obstacle contour parameters")
        self.frames = deque(maxlen=self.history_frames)
        self.tracker = StableClusterIds(timeout_sec=self.history_duration)
        self.previous_outline_ids = set()
        self.previous_gap_ids = set()
        self.previous_debug_ids = set()
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.cluster_pub = rospy.Publisher("/radar/obstacle_clusters", PointCloud2, queue_size=1)
        self.filtered_pub = rospy.Publisher("/radar/filtered_points", PointCloud2, queue_size=1)
        self.outline_pub = rospy.Publisher("/radar/obstacle_outlines", MarkerArray, queue_size=1)
        self.gap_pub = rospy.Publisher("/radar/traversable_gaps", MarkerArray, queue_size=1)
        self.heading_pub = rospy.Publisher("/radar/recommended_heading", Float32, queue_size=1)
        self.debug_pub = rospy.Publisher("/radar/obstacle_debug", MarkerArray, queue_size=1)
        self.subscriber = rospy.Subscriber("/radar/points", PointCloud2, self.callback, queue_size=10)

    def read_transformed(self, cloud):
        available = {field.name for field in cloud.fields}
        if not {"x", "y", "z"}.issubset(available):
            rospy.logwarn_throttle(5.0, "Obstacle contour input lacks x/y/z")
            return None, ()
        names = tuple(name for name in PREFERRED_FIELDS if name in available)
        transform = None
        if cloud.header.frame_id != self.frame_id:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.frame_id, cloud.header.frame_id, cloud.header.stamp,
                    rospy.Duration(0.1)).transform
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as exc:
                rospy.logwarn_throttle(2.0, "Obstacle contour TF unavailable: %s", exc)
                return None, names
        stamp = cloud.header.stamp.to_sec() if cloud.header.stamp != rospy.Time() else rospy.Time.now().to_sec()
        points = []
        for row in pc2.read_points(cloud, field_names=names, skip_nans=False):
            point = dict(zip(names, row))
            xyz = (point["x"], point["y"], point["z"])
            if transform is not None and all(math.isfinite(value) for value in xyz):
                xyz = rotate_translate_3d(
                    xyz, (transform.translation.x, transform.translation.y, transform.translation.z),
                    (transform.rotation.x, transform.rotation.y, transform.rotation.z, transform.rotation.w))
            point.update(x=xyz[0], y=xyz[1], z=xyz[2], stamp=stamp)
            if valid_point(point, self.valid_min_range, self.max_range,
                           self.min_z, self.max_z, self.min_snr, self.half_fov):
                points.append(point)
        return points, names

    def callback(self, cloud):
        points, names = self.read_transformed(cloud)
        if points is None:
            return
        now = cloud.header.stamp.to_sec() if cloud.header.stamp != rospy.Time() else rospy.Time.now().to_sec()
        self.frames.append((now, points))
        while self.frames and now - self.frames[0][0] > self.history_duration:
            self.frames.popleft()
        combined = voxel_downsample([point for _stamp, frame in self.frames for point in frame],
                                    self.voxel_size)
        combined.sort(key=lambda point: point.get("stamp", 0.0))
        if len(combined) > self.max_accumulated_points:
            combined = combined[-self.max_accumulated_points:]
        groups = euclidean_clusters(combined, self.cluster_eps, self.cluster_min_points,
                                    self.max_clusters)
        clusters = [describe_cluster(group) for group in groups]
        clusters, _expired = self.tracker.update(clusters, now)
        gaps = xy_gaps(clusters, self.half_fov, self.max_gap_depth_offset)
        candidates = traversable_xy_gaps(
            gaps, self.robot_width, self.safety_margin, self.min_gap_width)
        stamp = cloud.header.stamp if cloud.header.stamp != rospy.Time() else rospy.Time.now()
        self.publish_filtered(points, names, stamp)
        self.publish_cloud(clusters, names, stamp)
        self.publish_outlines(clusters, stamp)
        self.publish_gaps(candidates, stamp)
        self.publish_debug(combined, clusters, gaps, stamp)
        self.heading_pub.publish(Float32(candidates[0]["center_angle_deg"] if candidates else float("nan")))

    def publish_filtered(self, points, names, stamp):
        """Publish only this callback's valid points, before history accumulation."""
        output_names = tuple(name for name in PREFERRED_FIELDS if name in names)
        fields = [PointField(name=name, offset=index * 4,
                             datatype=PointField.FLOAT32, count=1)
                  for index, name in enumerate(output_names)]
        rows = [[float(point.get(name, float("nan"))) for name in output_names]
                for point in points]
        self.filtered_pub.publish(pc2.create_cloud(
            Header(stamp=stamp, frame_id=self.frame_id), fields, rows))

    def marker(self, namespace, marker_id, marker_type, stamp):
        item = Marker(header=Header(stamp=stamp, frame_id=self.frame_id), ns=namespace,
                      id=marker_id, type=marker_type, action=Marker.ADD)
        item.pose.orientation.w = 1.0
        item.lifetime = rospy.Duration(0.7)
        return item

    @staticmethod
    def delete_missing(array, namespaces, previous, current, stamp, frame_id):
        for marker_id in previous - current:
            for namespace in namespaces:
                item = Marker(header=Header(stamp=stamp, frame_id=frame_id), ns=namespace,
                              id=marker_id, action=Marker.DELETE)
                array.markers.append(item)

    def publish_cloud(self, clusters, names, stamp):
        output_names = tuple(name for name in PREFERRED_FIELDS if name in names) + ("cluster_id",)
        fields = [PointField(name=name, offset=index * 4, datatype=PointField.FLOAT32, count=1)
                  for index, name in enumerate(output_names)]
        rows = []
        for cluster in clusters:
            for point in cluster["points"]:
                rows.append([float(cluster["id"]) if name == "cluster_id" else
                             float(point.get(name, float("nan"))) for name in output_names])
        self.cluster_pub.publish(pc2.create_cloud(Header(stamp=stamp, frame_id=self.frame_id), fields, rows))

    def publish_outlines(self, clusters, stamp):
        array, current = MarkerArray(), {cluster["id"] for cluster in clusters}
        self.delete_missing(array, ("cluster_outline", "cluster_centroid"),
                            self.previous_outline_ids, current, stamp, self.frame_id)
        for cluster in clusters:
            cid, cx, cy, cz = cluster["id"], *cluster["centroid"]
            outline = self.marker("cluster_outline", cid, Marker.LINE_STRIP, stamp)
            outline.scale.x = 0.040
            outline.color.r, outline.color.g, outline.color.b, outline.color.a = 1.0, 0.18, 0.02, 1.0
            outline.points = [Point(x=x, y=y, z=max(0.04, cz)) for x, y in cluster["outline"]]
            if len(outline.points) > 2:
                outline.points.append(outline.points[0])
            centroid = self.marker("cluster_centroid", cid, Marker.SPHERE, stamp)
            centroid.pose.position = Point(cx, cy, max(0.08, cz))
            centroid.scale.x = centroid.scale.y = centroid.scale.z = 0.055
            centroid.color.r, centroid.color.g, centroid.color.b, centroid.color.a = 1.0, 0.55, 0.05, 1.0
            array.markers.extend((outline, centroid))
        self.previous_outline_ids = current
        self.outline_pub.publish(array)

    def publish_gaps(self, candidates, stamp):
        array, current = MarkerArray(), set(range(1, len(candidates) + 1))
        self.delete_missing(array, ("traversable_gap", "gap_label"), self.previous_gap_ids,
                            current, stamp, self.frame_id)
        for index, gap in enumerate(candidates, 1):
            radius = min(1.0, gap["nearest_obstacle_range_m"])
            wedge = self.marker("traversable_gap", index, Marker.LINE_LIST, stamp)
            wedge.scale.x = 0.055 if index == 1 else 0.032
            wedge.color.r, wedge.color.g, wedge.color.b, wedge.color.a = ((0.0, 0.95, 0.95, 1.0)
                                                                           if index == 1 else (0.20, 0.75, 0.55, 0.70))
            right = gap["right_boundary"]
            left = gap["left_boundary"]
            wedge.points.extend((Point(right[0], right[1], 0.05),
                                 Point(left[0], left[1], 0.05),
                                 Point(0, 0, 0.05),
                                 Point(gap["center"][0], gap["center"][1], 0.05)))
            label = self.marker("gap_label", index, Marker.TEXT_VIEW_FACING, stamp)
            angle = math.radians(gap["center_angle_deg"])
            label.pose.position = Point(0.65 * radius * math.cos(angle),
                                        0.65 * radius * math.sin(angle), 0.16)
            label.scale.z = 0.12
            label.color.r = label.color.g = label.color.b = label.color.a = 1.0
            label.text = "XY {:.2f}m conf {:.2f}".format(gap["estimated_width_m"], gap["confidence"])
            array.markers.extend((wedge, label))
        if candidates:
            best = candidates[0]
            arrow = self.marker("recommended_heading", 0, Marker.ARROW, stamp)
            angle = math.radians(best["center_angle_deg"])
            arrow.points = [Point(0, 0, 0.12), Point(0.9 * math.cos(angle), 0.9 * math.sin(angle), 0.12)]
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.075, 0.14, 0.17
            arrow.color.r, arrow.color.g, arrow.color.b, arrow.color.a = 0.0, 1.0, 0.92, 1.0
            array.markers.append(arrow)
        elif self.previous_gap_ids:
            item = Marker(header=Header(stamp=stamp, frame_id=self.frame_id),
                          ns="recommended_heading", id=0, action=Marker.DELETE)
            array.markers.append(item)
        self.previous_gap_ids = current
        self.gap_pub.publish(array)

    def publish_debug(self, points, clusters, gaps, stamp):
        array = MarkerArray()
        raw = self.marker("debug_filtered", 0, Marker.SPHERE_LIST, stamp)
        raw.scale.x = raw.scale.y = raw.scale.z = 0.035
        raw.color.r, raw.color.g, raw.color.b, raw.color.a = 0.65, 0.65, 0.65, 0.65
        raw.points = [Point(p["x"], p["y"], p["z"]) for p in points]
        array.markers.append(raw)
        for cluster in clusters:
            cid, cx, cy, cz = cluster["id"], *cluster["centroid"]
            label = self.marker("debug_cluster_label", cid, Marker.TEXT_VIEW_FACING, stamp)
            label.pose.position = Point(cx, cy, max(0.18, cz + 0.14))
            label.scale.z = 0.085
            label.color.r = label.color.g = label.color.b = label.color.a = 0.9
            label.text = "C{} N={} W={:.2f}m".format(
                cid, cluster["count"], cluster["width_m"])
            array.markers.append(label)
        current = set()
        for index, gap in enumerate(gaps, 1):
            current.add(index)
            text = self.marker("debug_gap", index, Marker.TEXT_VIEW_FACING, stamp)
            if gap.get("kind") == "internal":
                angle = math.radians(gap["center_angle_deg"])
            elif "start_angle_deg" in gap:
                angle = math.radians(0.5 * (gap["start_angle_deg"] + gap["end_angle_deg"]))
            else:
                angle = 0.0
            text.pose.position = Point(0.45 * math.cos(angle), 0.45 * math.sin(angle), 0.28)
            text.scale.z = 0.09
            text.color.r, text.color.g, text.color.b, text.color.a = 0.8, 0.8, 0.8, 0.8
            if gap.get("kind") == "internal":
                text.text = "XY gap {:.2f}m c={:.2f}".format(
                    gap["estimated_width_m"], gap["confidence"])
            else:
                text.text = "{} UNKNOWN".format(gap.get("side", "depth mismatch").upper())
            array.markers.append(text)
        self.delete_missing(array, ("debug_gap",), self.previous_debug_ids, current, stamp, self.frame_id)
        self.previous_debug_ids = current
        self.debug_pub.publish(array)


if __name__ == "__main__":
    rospy.init_node("radar_obstacle_contour")
    RadarObstacleContour()
    rospy.spin()
