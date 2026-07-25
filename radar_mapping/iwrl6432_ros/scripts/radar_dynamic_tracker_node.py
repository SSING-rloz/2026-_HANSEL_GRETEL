#!/usr/bin/env python3
"""Doppler-based dynamic-object clustering and lightweight ID tracking.

Doppler is radial velocity relative to a stationary radar.  It is not a full
three-dimensional velocity vector; marker arrows only visualize its signed
radial direction.
"""

import math
from collections import deque

import rospy
import sensor_msgs.point_cloud2 as pc2
from geometry_msgs.msg import Point
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import ColorRGBA, Header
from visualization_msgs.msg import Marker, MarkerArray


POINT_FIELDS = ("x", "y", "z", "doppler", "snr")
BOUNDARY_TOLERANCE = 1e-5
MARKER_NAMESPACES = ("dynamic_centroid", "dynamic_box", "dynamic_doppler", "dynamic_text")


def filter_dynamic_points(points, min_range=0.2, max_range=3.0,
                          min_elevation=-10.0, max_elevation=60.0,
                          min_snr=15.0, min_abs_doppler=0.15,
                          max_abs_doppler=5.0):
    """Return finite points passing inclusive geometry/SNR/Doppler limits."""
    accepted = []
    for source in points:
        try:
            point = {name: float(source[name]) for name in POINT_FIELDS}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(point[name]) for name in POINT_FIELDS):
            continue
        distance = math.sqrt(point["x"] ** 2 + point["y"] ** 2 + point["z"] ** 2)
        horizontal = math.hypot(point["x"], point["y"])
        elevation = math.degrees(math.atan2(point["z"], horizontal))
        abs_doppler = abs(point["doppler"])
        if (min_range - BOUNDARY_TOLERANCE <= distance <= max_range + BOUNDARY_TOLERANCE and
                min_elevation - BOUNDARY_TOLERANCE <= elevation <=
                max_elevation + BOUNDARY_TOLERANCE and
                point["snr"] >= min_snr and
                min_abs_doppler - BOUNDARY_TOLERANCE <= abs_doppler <=
                max_abs_doppler + BOUNDARY_TOLERANCE):
            accepted.append(point)
    return accepted


def euclidean_clusters(points, distance_threshold, min_points):
    """Connected-component clustering with a 3D Euclidean neighbor graph."""
    if distance_threshold <= 0.0 or min_points <= 0:
        raise ValueError("cluster distance and minimum points must be positive")
    threshold_squared = distance_threshold ** 2
    unseen = set(range(len(points)))
    clusters = []
    while unseen:
        seed = unseen.pop()
        component = [seed]
        pending = [seed]
        while pending:
            current = pending.pop()
            origin = points[current]
            neighbors = []
            for candidate in unseen:
                other = points[candidate]
                squared = sum((origin[axis] - other[axis]) ** 2
                              for axis in ("x", "y", "z"))
                if squared <= threshold_squared:
                    neighbors.append(candidate)
            for candidate in neighbors:
                unseen.remove(candidate)
                component.append(candidate)
                pending.append(candidate)
        if len(component) >= min_points:
            clusters.append(cluster_statistics([points[index] for index in component]))
    return clusters


def cluster_statistics(points):
    count = len(points)
    centroid = tuple(sum(point[axis] for point in points) / count
                     for axis in ("x", "y", "z"))
    minimum = tuple(min(point[axis] for point in points) for axis in ("x", "y", "z"))
    maximum = tuple(max(point[axis] for point in points) for axis in ("x", "y", "z"))
    return {
        "centroid": centroid,
        "minimum": minimum,
        "maximum": maximum,
        "doppler": sum(point["doppler"] for point in points) / count,
        "snr": sum(point["snr"] for point in points) / count,
        "range": math.sqrt(sum(value ** 2 for value in centroid)),
        "count": count,
    }


class TrackManager:
    """Greedy nearest-neighbor association without motion prediction."""

    def __init__(self, association_distance=0.7, timeout=1.0):
        self.association_distance = association_distance
        self.timeout = timeout
        self.tracks = {}
        self.next_id = 1

    def update(self, clusters, stamp_sec):
        expired = self.expire(stamp_sec)
        candidates = []
        for track_id, track in self.tracks.items():
            for cluster_index, cluster in enumerate(clusters):
                distance = math.sqrt(sum(
                    (track["centroid"][axis] - cluster["centroid"][axis]) ** 2
                    for axis in range(3)))
                if distance <= self.association_distance:
                    candidates.append((distance, track_id, cluster_index))
        assigned_tracks = set()
        assigned_clusters = set()
        cluster_to_track = {}
        for _distance, track_id, cluster_index in sorted(candidates):
            if track_id in assigned_tracks or cluster_index in assigned_clusters:
                continue
            self.tracks[track_id] = dict(clusters[cluster_index], last_seen=stamp_sec)
            assigned_tracks.add(track_id)
            assigned_clusters.add(cluster_index)
            cluster_to_track[cluster_index] = track_id
        visible = []
        for cluster_index, cluster in enumerate(clusters):
            if cluster_index not in assigned_clusters:
                track_id = self.next_id
                self.next_id += 1
                self.tracks[track_id] = dict(cluster, last_seen=stamp_sec)
            else:
                track_id = cluster_to_track[cluster_index]
            visible.append((track_id, self.tracks[track_id]))
        return visible, expired

    def expire(self, stamp_sec):
        expired = [track_id for track_id, track in self.tracks.items()
                   if stamp_sec - track["last_seen"] >= self.timeout]
        for track_id in expired:
            del self.tracks[track_id]
        return expired


def marker_deletions(track_ids, frame_id, stamp):
    result = MarkerArray()
    for track_id in track_ids:
        for namespace in MARKER_NAMESPACES:
            marker = Marker()
            marker.header = Header(frame_id=frame_id, stamp=stamp)
            marker.ns = namespace
            marker.id = track_id
            marker.action = Marker.DELETE
            result.markers.append(marker)
    return result


class RadarDynamicTracker:
    def __init__(self):
        self.min_range = float(rospy.get_param("~min_range_m", 0.2))
        self.max_range = float(rospy.get_param("~max_range_m", 3.0))
        self.min_elevation = float(rospy.get_param("~min_elevation_deg", -10.0))
        self.max_elevation = float(rospy.get_param("~max_elevation_deg", 60.0))
        self.min_snr = float(rospy.get_param("~min_snr_db", 15.0))
        self.min_abs_doppler = float(rospy.get_param("~min_abs_doppler_mps", 0.15))
        self.max_abs_doppler = float(rospy.get_param("~max_abs_doppler_mps", 5.0))
        self.history_frames = int(rospy.get_param("~history_frames", 3))
        self.cluster_distance = float(rospy.get_param("~cluster_distance_m", 0.45))
        self.min_cluster_points = int(rospy.get_param("~min_cluster_points", 2))
        association = float(rospy.get_param("~association_distance_m", 0.7))
        self.track_timeout = float(rospy.get_param("~track_timeout_sec", 1.0))
        if not (0.0 <= self.min_range < self.max_range and
                self.min_elevation <= self.max_elevation and self.min_snr >= 0.0 and
                0.0 <= self.min_abs_doppler <= self.max_abs_doppler and
                self.history_frames > 0 and self.cluster_distance > 0.0 and
                self.min_cluster_points > 0 and association > 0.0 and self.track_timeout > 0.0):
            raise ValueError("invalid dynamic tracker parameters")
        self.frames = deque()
        self.tracker = TrackManager(association, self.track_timeout)
        self.last_frame_id = ""
        self.dynamic_pub = rospy.Publisher(
            "/radar/dynamic_points_3d", PointCloud2, queue_size=10)
        self.marker_pub = rospy.Publisher(
            "/radar/dynamic_markers", MarkerArray, queue_size=10)
        self.subscriber = rospy.Subscriber(
            "/radar/points", PointCloud2, self.cloud_callback, queue_size=20)

    @staticmethod
    def dictionaries_from_cloud(message):
        available = {field.name for field in message.fields}
        if not {"x", "y", "z"}.issubset(available):
            rospy.logwarn_throttle(5.0, "Dynamic tracker: PointCloud2 has no complete x/y/z fields")
            return None
        if "doppler" not in available:
            rospy.logwarn_throttle(5.0, "Dynamic tracker: PointCloud2 has no Doppler field")
            return None
        if "snr" not in available:
            rospy.logwarn_throttle(5.0, "Dynamic tracker: PointCloud2 has no SNR field")
            return None
        rows = pc2.read_points(message, field_names=POINT_FIELDS, skip_nans=False)
        return [dict(zip(POINT_FIELDS, row)) for row in rows]

    @staticmethod
    def make_cloud(points, frame_id, stamp):
        fields = [PointField(name=name, offset=index * 4,
                             datatype=PointField.FLOAT32, count=1)
                  for index, name in enumerate(POINT_FIELDS)]
        rows = [[point[name] for name in POINT_FIELDS] for point in points]
        return pc2.create_cloud(Header(frame_id=frame_id, stamp=stamp), fields, rows)

    def prune_frames(self, stamp_sec):
        while self.frames and stamp_sec - self.frames[0][0] >= self.track_timeout:
            self.frames.popleft()
        while len(self.frames) > self.history_frames:
            self.frames.popleft()

    def cloud_callback(self, message):
        stamp = message.header.stamp
        if stamp == rospy.Time():
            stamp = rospy.Time.now()
        stamp_sec = stamp.to_sec()
        frame_id = message.header.frame_id
        self.last_frame_id = frame_id
        raw = self.dictionaries_from_cloud(message)
        dynamic = [] if raw is None else filter_dynamic_points(
            raw, self.min_range, self.max_range, self.min_elevation,
            self.max_elevation, self.min_snr, self.min_abs_doppler,
            self.max_abs_doppler)
        self.frames.append((stamp_sec, dynamic))
        self.prune_frames(stamp_sec)
        combined = [point for _frame_stamp, frame in self.frames for point in frame]
        self.dynamic_pub.publish(self.make_cloud(combined, frame_id, stamp))
        clusters = euclidean_clusters(
            combined, self.cluster_distance, self.min_cluster_points)
        visible, expired = self.tracker.update(clusters, stamp_sec)
        markers = self.build_markers(visible, frame_id, stamp)
        markers.markers.extend(marker_deletions(expired, frame_id, stamp).markers)
        self.marker_pub.publish(markers)

    @staticmethod
    def base_marker(track_id, namespace, marker_type, frame_id, stamp, color):
        marker = Marker()
        marker.header = Header(frame_id=frame_id, stamp=stamp)
        marker.ns = namespace
        marker.id = track_id
        marker.type = marker_type
        marker.action = Marker.ADD
        marker.pose.orientation.w = 1.0
        marker.color = color
        marker.lifetime = rospy.Duration(0)
        return marker

    def build_markers(self, visible_tracks, frame_id, stamp):
        result = MarkerArray()
        for track_id, track in visible_tracks:
            cx, cy, cz = track["centroid"]
            minimum, maximum = track["minimum"], track["maximum"]
            centroid = self.base_marker(
                track_id, "dynamic_centroid", Marker.SPHERE, frame_id, stamp,
                ColorRGBA(1.0, 0.2, 0.1, 0.95))
            centroid.pose.position = Point(cx, cy, cz)
            centroid.scale.x = centroid.scale.y = centroid.scale.z = 0.12
            result.markers.append(centroid)

            box = self.base_marker(
                track_id, "dynamic_box", Marker.CUBE, frame_id, stamp,
                ColorRGBA(1.0, 0.65, 0.05, 0.22))
            box.pose.position = Point(*(0.5 * (minimum[index] + maximum[index])
                                        for index in range(3)))
            box.scale.x = max(0.15, maximum[0] - minimum[0])
            box.scale.y = max(0.15, maximum[1] - minimum[1])
            box.scale.z = max(0.15, maximum[2] - minimum[2])
            result.markers.append(box)

            arrow = self.base_marker(
                track_id, "dynamic_doppler", Marker.ARROW, frame_id, stamp,
                ColorRGBA(0.2, 0.9, 1.0, 0.95))
            radial_range = max(track["range"], 1e-6)
            signed_length = max(-0.8, min(0.8, track["doppler"] * 0.25))
            arrow.points = [Point(cx, cy, cz), Point(
                cx + cx / radial_range * signed_length,
                cy + cy / radial_range * signed_length,
                cz + cz / radial_range * signed_length)]
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.035, 0.075, 0.11
            result.markers.append(arrow)

            text = self.base_marker(
                track_id, "dynamic_text", Marker.TEXT_VIEW_FACING, frame_id, stamp,
                ColorRGBA(1.0, 1.0, 1.0, 1.0))
            text.pose.position = Point(cx, cy, maximum[2] + 0.22)
            text.scale.z = 0.14
            text.text = "ID {}\nR={:.2f} m\nVr={:+.2f} m/s\nN={}".format(
                track_id, track["range"], track["doppler"], track["count"])
            result.markers.append(text)
        return result


def main():
    rospy.init_node("radar_dynamic_tracker")
    RadarDynamicTracker()
    rospy.spin()


if __name__ == "__main__":
    main()
