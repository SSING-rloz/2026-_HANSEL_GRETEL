#!/usr/bin/env python3
"""Publish current-frame 3D radar points and persistent angular-sector risk."""

from collections import deque
import math
import os

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from geometry_msgs.msg import Point
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Float32, Float32MultiArray, Header
from visualization_msgs.msg import Marker, MarkerArray

from iwrl6432_ros.manual_pose_mapping import rotate_translate_3d
from iwrl6432_ros.sector_occupancy import (
    POINT_FIELDS, corridor_to_array, load_background_profile,
    matches_background_voxel, persistence_statistics, recommended_sector,
    risk_score, sector_bounds,
    sector_index, select_low_occupancy_corridor, summarize_sector,
    valid_near_field_point, within_vertical_roi,
)


class RadarSectorOccupancy:
    def __init__(self):
        gp = rospy.get_param
        self.frame_id = str(gp("~frame_id", "base_link"))
        self.min_range = float(gp("~valid_min_range_m", 0.10))
        self.max_range = float(gp("~max_range_m", 1.00))
        self.min_snr = float(gp("~min_snr_db", 8.0))
        self.half_fov = math.radians(0.5 * float(gp("~front_fov_deg", 120.0)))
        self.sector_count = int(gp("~sector_count", 5))
        self.persistence_frames = int(gp("~persistence_frames", 3))
        self.sector_voxel_size = float(gp("~voxel_size_m", 0.02))
        self.density_saturation = float(gp("~density_saturation_voxels", 3.0))
        self.weights = (float(gp("~presence_weight", 0.50)),
                        float(gp("~distance_weight", 0.35)),
                        float(gp("~density_weight", 0.15)))
        self.occupied_threshold = float(gp("~occupied_threshold", 0.55))
        self.minimum_clear_count = int(gp("~minimum_clear_sector_count", 1))
        self.enable_corridor = bool(gp("~enable_low_occupancy_corridor", True))
        self.corridor_inner_range = float(gp(
            "~corridor_inner_range_m", 0.10))
        self.corridor_outer_range = float(gp(
            "~corridor_outer_range_m", 1.00))
        self.corridor_floor_z = float(gp("~corridor_floor_z_m", 0.00))
        self.corridor_marker_alpha = float(gp("~corridor_marker_alpha", 0.15))
        self.show_sector_3d_guide = bool(gp("~show_sector_3d_guide", True))
        self.sector_3d_min_z = float(gp("~sector_3d_min_z_m", -0.40))
        self.sector_3d_max_z = float(gp("~sector_3d_max_z_m", 0.40))
        self.profile_path = os.path.expanduser(str(gp(
            "~background_profile_path",
            "/tmp/iwrl6432_sector_occupancy/background_profile.yaml")))
        self.background_neighbor_radius = int(gp(
            "~background_neighbor_voxel_radius", 0))
        self.sector_min_z = float(gp("~sector_min_z", float("-inf")))
        self.sector_max_z = float(gp("~sector_max_z", float("inf")))
        if not (0 < self.min_range < self.max_range and self.min_snr >= 0 and
                0 < self.half_fov <= math.pi / 2 and self.sector_count > 0 and
                self.persistence_frames > 0 and self.sector_voxel_size > 0 and
                self.density_saturation > 0 and 0 <= self.occupied_threshold <= 1 and
                self.minimum_clear_count > 0 and
                self.background_neighbor_radius >= 0 and
                not math.isnan(self.sector_min_z) and
                not math.isnan(self.sector_max_z) and
                self.sector_min_z <= self.sector_max_z and
                0 <= self.corridor_inner_range < self.corridor_outer_range and
                0 <= self.corridor_marker_alpha <= 1 and
                self.sector_3d_min_z < self.sector_3d_max_z):
            raise ValueError(
                "invalid sector occupancy parameters; sector_min_z must not "
                "exceed sector_max_z")
        if (abs(self.corridor_inner_range - self.min_range) > 1e-9 or
                abs(self.corridor_outer_range - self.max_range) > 1e-9):
            rospy.logwarn(
                "Low-occupancy corridor range [%.3f, %.3f] differs from "
                "valid sector range [%.3f, %.3f]",
                self.corridor_inner_range, self.corridor_outer_range,
                self.min_range, self.max_range)
        _risk, _distance, _density, normalized = risk_score(
            0.0, float("nan"), 0.0, self.min_range, self.max_range,
            self.density_saturation, self.weights)
        if any(abs(a - b) > 1e-9 for a, b in zip(self.weights, normalized)):
            rospy.logwarn("Sector risk weights sum to %.6f; normalized to %s",
                          sum(self.weights), normalized)
        self.weights = normalized
        self.bounds = sector_bounds(self.half_fov, self.sector_count)
        self.history = [deque(maxlen=self.persistence_frames)
                        for _ in range(self.sector_count)]
        self.background_voxel_size = None
        self.background_voxels = set()
        self.previous_nearest_ids = set()
        self.heading_visible = False
        self.load_profile()
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.sector_points_pub = rospy.Publisher(
            "/radar/sector_points", PointCloud2, queue_size=1)
        self.background_points_pub = rospy.Publisher(
            "/radar/background_points", PointCloud2, queue_size=1)
        self.occupancy_pub = rospy.Publisher(
            "/radar/sector_occupancy", Float32MultiArray, queue_size=1)
        self.nearest_pub = rospy.Publisher(
            "/radar/sector_nearest_ranges", Float32MultiArray, queue_size=1)
        self.heading_pub = rospy.Publisher(
            "/radar/sector_recommended_heading", Float32, queue_size=1)
        self.corridor_pub = rospy.Publisher(
            "/radar/low_occupancy_corridor", Float32MultiArray, queue_size=1)
        self.corridor_marker_pub = rospy.Publisher(
            "/radar/low_occupancy_corridor_markers", MarkerArray, queue_size=1)
        self.marker_pub = rospy.Publisher(
            "/radar/sector_markers", MarkerArray, queue_size=1)
        self.subscriber = rospy.Subscriber(
            "/radar/points", PointCloud2, self.callback, queue_size=10)

    def load_profile(self):
        try:
            size, voxels, _document = load_background_profile(
                self.profile_path, self.frame_id)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            rospy.logwarn("Background profile unavailable (%s); subtraction disabled", exc)
            return
        self.background_voxel_size = size
        self.background_voxels = voxels
        rospy.loginfo("Loaded %d background voxels (%.3f m) from %s",
                      len(voxels), size, self.profile_path)
        rospy.loginfo("Background matching uses neighbor voxel radius %d",
                      self.background_neighbor_radius)

    def read_transformed(self, cloud):
        available = {field.name for field in cloud.fields}
        if not {"x", "y", "z"}.issubset(available):
            rospy.logwarn_throttle(5.0, "Sector occupancy input lacks x/y/z")
            return None, ()
        names = tuple(name for name in POINT_FIELDS if name in available)
        transform = None
        if cloud.header.frame_id != self.frame_id:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.frame_id, cloud.header.frame_id, cloud.header.stamp,
                    rospy.Duration(0.1)).transform
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as exc:
                rospy.logwarn_throttle(2.0, "Sector occupancy TF unavailable: %s", exc)
                return None, names
        points = []
        for values in pc2.read_points(cloud, field_names=names, skip_nans=False):
            point = dict(zip(names, values))
            xyz = (point["x"], point["y"], point["z"])
            if transform is not None and all(math.isfinite(value) for value in xyz):
                xyz = rotate_translate_3d(
                    xyz, (transform.translation.x, transform.translation.y,
                          transform.translation.z),
                    (transform.rotation.x, transform.rotation.y,
                     transform.rotation.z, transform.rotation.w))
            point.update(x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]))
            if valid_near_field_point(point, self.min_range, self.max_range,
                                      self.min_snr, math.degrees(self.half_fov)):
                points.append(point)
        return points, names

    def cloud(self, points, stamp):
        fields = [PointField(name=name, offset=index * 4,
                             datatype=PointField.FLOAT32, count=1)
                  for index, name in enumerate(POINT_FIELDS)]
        rows = [[float(point.get(name, float("nan"))) for name in POINT_FIELDS]
                for point in points]
        return pc2.create_cloud(Header(stamp=stamp, frame_id=self.frame_id), fields, rows)

    def callback(self, cloud):
        points, _names = self.read_transformed(cloud)
        if points is None:
            return
        current, background = [], []
        for point in points:
            is_background = (self.background_voxel_size is not None and
                             matches_background_voxel(
                                 point, self.background_voxel_size,
                                 self.background_voxels,
                                 self.background_neighbor_radius))
            (background if is_background else current).append(point)
        sectors = [[] for _ in range(self.sector_count)]
        sector_input = [point for point in current if within_vertical_roi(
            point, self.sector_min_z, self.sector_max_z)]
        for point in sector_input:
            index = sector_index(math.atan2(point["y"], point["x"]),
                                 self.half_fov, self.sector_count)
            if index is not None:
                sectors[index].append(point)
        risks, nearest_ranges, occupied, persistent = [], [], [], []
        for index, sector_points in enumerate(sectors):
            summary = summarize_sector(sector_points, self.sector_voxel_size)
            self.history[index].append(summary)
            presence, nearest, median_voxels = persistence_statistics(self.history[index])
            risk, _distance, _density, _weights = risk_score(
                presence, nearest, median_voxels, self.min_range, self.max_range,
                self.density_saturation, self.weights)
            risks.append(risk)
            nearest_ranges.append(nearest)
            occupied.append(risk >= self.occupied_threshold)
            persistent.append((presence, median_voxels))
        selected = recommended_sector(
            risks, nearest_ranges, occupied, self.minimum_clear_count)
        heading = (float("nan") if selected is None else
                   0.5 * (self.bounds[selected][0] + self.bounds[selected][1]))
        corridor = (select_low_occupancy_corridor(
            risks, nearest_ranges, occupied, self.bounds, heading)
                    if self.enable_corridor else None)
        if (corridor is not None and math.isfinite(heading) and
                not corridor["recommended_heading_inside"]):
            rospy.logwarn_throttle(
                2.0, "Existing recommended heading %.1f deg is outside selected "
                "low-occupancy corridor S%d-S%d; existing heading is unchanged",
                math.degrees(heading), corridor["start_index"] + 1,
                corridor["end_index"] + 1)
        stamp = cloud.header.stamp if cloud.header.stamp != rospy.Time() else rospy.Time.now()
        self.sector_points_pub.publish(self.cloud(sector_input, stamp))
        self.background_points_pub.publish(self.cloud(background, stamp))
        self.occupancy_pub.publish(Float32MultiArray(data=risks))
        self.nearest_pub.publish(Float32MultiArray(data=nearest_ranges))
        self.heading_pub.publish(Float32(heading))
        self.corridor_pub.publish(Float32MultiArray(
            data=corridor_to_array(corridor)))
        self.publish_markers(sectors, risks, nearest_ranges, occupied,
                             persistent, selected, stamp)
        self.publish_corridor_markers(corridor, heading, stamp)

    def marker(self, namespace, marker_id, marker_type, stamp):
        marker = Marker(header=Header(stamp=stamp, frame_id=self.frame_id),
                        ns=namespace, id=marker_id, type=marker_type,
                        action=Marker.ADD)
        marker.pose.orientation.w = 1.0
        marker.lifetime = rospy.Duration(0.5)
        return marker

    def delete_marker(self, namespace, marker_id, stamp):
        """Return a well-formed DELETE marker with an identity orientation."""
        marker = self.marker(namespace, marker_id, Marker.LINE_LIST, stamp)
        marker.action = Marker.DELETE
        return marker

    @staticmethod
    def polar_point(radius, angle, z_value):
        return Point(radius * math.cos(angle), radius * math.sin(angle), z_value)

    def wireframe_points(self, left_angle, right_angle, z_min=-0.40, z_max=0.40):
        """Return only outer upper/lower arc segments for a minimal 3D guide."""
        points = []
        steps = 6
        for z_value in (z_min, z_max):
            previous = self.polar_point(self.max_range, left_angle, z_value)
            for step in range(1, steps + 1):
                angle = left_angle + (right_angle - left_angle) * step / steps
                current = self.polar_point(self.max_range, angle, z_value)
                points.extend((previous, current))
                previous = current
        return points

    def corridor_floor_points(self, start_angle, end_angle):
        """Build a thin annular sector; this indicates direction, not clearance."""
        points = []
        steps = max(2, int(math.ceil(abs(start_angle - end_angle) /
                                     math.radians(6.0))))
        for step in range(steps):
            first = start_angle + (end_angle - start_angle) * step / steps
            second = start_angle + (end_angle - start_angle) * (step + 1) / steps
            inner_first = self.polar_point(
                self.corridor_inner_range, first, self.corridor_floor_z)
            outer_first = self.polar_point(
                self.corridor_outer_range, first, self.corridor_floor_z)
            inner_second = self.polar_point(
                self.corridor_inner_range, second, self.corridor_floor_z)
            outer_second = self.polar_point(
                self.corridor_outer_range, second, self.corridor_floor_z)
            points.extend((inner_first, outer_first, outer_second,
                           inner_first, outer_second, inner_second))
        return points

    def publish_corridor_markers(self, corridor, recommended_heading, stamp):
        """Publish a low-return direction aid, not a vehicle-safe path."""
        array = MarkerArray()
        namespaces = ("low_occupancy_floor", "low_occupancy_boundary",
                      "low_occupancy_centerline", "low_occupancy_arrow",
                      "low_occupancy_text")
        if corridor is None:
            for namespace in namespaces:
                if namespace == "low_occupancy_text" and self.enable_corridor:
                    continue
                array.markers.append(self.delete_marker(namespace, 0, stamp))
            if self.enable_corridor:
                text = self.marker(
                    "low_occupancy_text", 0, Marker.TEXT_VIEW_FACING, stamp)
                text.pose.position = Point(0.82, 0, self.corridor_floor_z + 0.26)
                text.scale.z = 0.030
                text.color.r, text.color.g, text.color.b, text.color.a = (
                    1.0, 0.18, 0.10, 0.95)
                text.text = "PATH: NONE"
                array.markers.append(text)
            self.corridor_marker_pub.publish(array)
            return

        start_angle = corridor["start_angle_rad"]
        end_angle = corridor["end_angle_rad"]
        center_heading = corridor["center_heading_rad"]

        floor = self.marker(
            "low_occupancy_floor", 0, Marker.TRIANGLE_LIST, stamp)
        floor.color.r, floor.color.g, floor.color.b, floor.color.a = (
            0.08, 0.72, 0.92, self.corridor_marker_alpha)
        floor.points = self.corridor_floor_points(start_angle, end_angle)
        array.markers.append(floor)

        boundary = self.marker(
            "low_occupancy_boundary", 0, Marker.LINE_LIST, stamp)
        boundary.scale.x = 0.005
        boundary.color.r, boundary.color.g, boundary.color.b, boundary.color.a = (
            0.12, 0.82, 1.0, 0.78)
        boundary.points = []
        for angle in (start_angle, end_angle):
            boundary.points.extend((
                self.polar_point(self.corridor_inner_range, angle,
                                 self.corridor_floor_z + 0.004),
                self.polar_point(self.corridor_outer_range, angle,
                                 self.corridor_floor_z + 0.004)))
        array.markers.append(boundary)

        array.markers.append(self.delete_marker(
            "low_occupancy_centerline", 0, stamp))

        # Preserve and display the existing recommended heading only when it
        # lies inside the independently selected low-occupancy corridor.
        if (math.isfinite(recommended_heading) and
                corridor["recommended_heading_inside"]):
            arrow = self.marker(
                "low_occupancy_arrow", 0, Marker.ARROW, stamp)
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.015, 0.040, 0.070
            arrow.color.r, arrow.color.g, arrow.color.b, arrow.color.a = (
                0.95, 0.90, 0.12, 1.0)
            arrow.points = (
                self.polar_point(self.corridor_inner_range, recommended_heading,
                                 self.corridor_floor_z + 0.025),
                self.polar_point(min(self.corridor_inner_range + 0.65,
                                     self.corridor_outer_range),
                                 recommended_heading,
                                 self.corridor_floor_z + 0.025))
            array.markers.append(arrow)
        else:
            array.markers.append(self.delete_marker(
                "low_occupancy_arrow", 0, stamp))

        start_sector = corridor["start_index"] + 1
        end_sector = corridor["end_index"] + 1
        sector_text = ("S{}".format(start_sector) if start_sector == end_sector
                       else "S{}-S{}".format(start_sector, end_sector))
        text = self.marker(
            "low_occupancy_text", 0, Marker.TEXT_VIEW_FACING, stamp)
        text.pose.position = Point(0.82, 0, self.corridor_floor_z + 0.26)
        text.scale.z = 0.030
        text.color.r, text.color.g, text.color.b, text.color.a = (
            0.78, 0.96, 1.0, 0.96)
        text.text = "PATH: {} / {:.1f} deg".format(
            sector_text, math.degrees(center_heading))
        array.markers.append(text)
        self.corridor_marker_pub.publish(array)

    def publish_markers(self, sectors, risks, nearest_ranges, occupied,
                        persistent, selected, stamp):
        array = MarkerArray()
        boundary = self.marker("sector_boundaries", 0, Marker.LINE_LIST, stamp)
        boundary.scale.x = 0.005
        boundary.color.r, boundary.color.g, boundary.color.b, boundary.color.a = (
            0.62, 0.68, 0.74, 0.62)
        angles = [self.bounds[0][0]] + [right for _left, right in self.bounds]
        for angle in angles:
            boundary.points.extend((
                self.polar_point(self.min_range, angle, 0.004),
                self.polar_point(self.max_range, angle, 0.004)))
        array.markers.append(boundary)

        for index, (left_angle, right_angle) in enumerate(self.bounds):
            floor = self.marker("occupied_sector_floor", index,
                                Marker.TRIANGLE_LIST, stamp)
            if occupied[index]:
                floor.color.r, floor.color.g, floor.color.b, floor.color.a = (
                    1.0, 0.16, 0.08, 0.10)
                center_angle = 0.5 * (left_angle + right_angle)
                for first, second in ((left_angle, center_angle),
                                      (center_angle, right_angle)):
                    floor.points.extend((
                        self.polar_point(self.min_range, first, 0.001),
                        self.polar_point(self.max_range, first, 0.001),
                        self.polar_point(self.max_range, second, 0.001),
                        self.polar_point(self.min_range, first, 0.001),
                        self.polar_point(self.max_range, second, 0.001),
                        self.polar_point(self.min_range, second, 0.001)))
                array.markers.append(floor)
            else:
                floor.action = Marker.DELETE
                array.markers.append(floor)

        guide = self.marker("sector_3d_guide", 0, Marker.LINE_LIST, stamp)
        if self.show_sector_3d_guide:
            guide.scale.x = 0.0035
            guide.color.r, guide.color.g, guide.color.b, guide.color.a = (
                0.62, 0.65, 0.68, 0.20)
            for left_angle, right_angle in self.bounds:
                guide.points.extend(self.wireframe_points(
                    left_angle, right_angle,
                    self.sector_3d_min_z, self.sector_3d_max_z))
            # The six sector boundaries are shared, so each outer vertical is
            # emitted exactly once rather than once per adjacent sector.
            for angle in angles:
                guide.points.extend((
                    self.polar_point(self.max_range, angle,
                                     self.sector_3d_min_z),
                    self.polar_point(self.max_range, angle,
                                     self.sector_3d_max_z)))
            array.markers.append(guide)
        else:
            guide.action = Marker.DELETE
            array.markers.append(guide)

        guide_text = self.marker("sector_3d_guide_text", 0,
                                 Marker.TEXT_VIEW_FACING, stamp)
        if self.show_sector_3d_guide:
            guide_text.pose.position = Point(0.30, 0.35, 0.46)
            guide_text.scale.z = 0.024
            guide_text.color.r, guide_text.color.g = 0.70, 0.73
            guide_text.color.b, guide_text.color.a = 0.76, 0.68
            guide_text.text = "3D GUIDE: z = {:.1f} ~ {:+.1f} m".format(
                self.sector_3d_min_z, self.sector_3d_max_z)
            array.markers.append(guide_text)
        else:
            guide_text.action = Marker.DELETE
            array.markers.append(guide_text)

        summary = self.marker("sector_summary", 0,
                              Marker.TEXT_VIEW_FACING, stamp)
        summary.pose.position = Point(0.92, 0, 0.34)
        summary.scale.z = 0.030
        summary.color.r = summary.color.g = summary.color.b = 0.94
        summary.color.a = 0.96
        summary.text = " | ".join(
            "S{} {}".format(index + 1, "OCC" if state else "CLEAR")
            for index, state in enumerate(occupied))
        array.markers.append(summary)

        # Explicitly clear the legacy 3D boxes, per-sector labels/nearest dots,
        # cyan heading arrow, and BLOCKED text from this topic.
        for namespace in ("sector_wireframe", "sector_floor", "sector_status",
                          "sector_nearest"):
            for index in range(self.sector_count):
                array.markers.append(self.delete_marker(
                    namespace, index, stamp))
        for namespace in ("sector_recommended_heading", "sector_blocked"):
            array.markers.append(self.delete_marker(namespace, 0, stamp))
        self.marker_pub.publish(array)


def main():
    rospy.init_node("radar_sector_occupancy")
    RadarSectorOccupancy()
    rospy.spin()


if __name__ == "__main__":
    main()
