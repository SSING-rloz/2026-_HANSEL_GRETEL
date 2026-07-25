#!/usr/bin/env python3
"""Publish sparse-radar obstacle contour, local free space, grid, and headings."""

from collections import deque
import math

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from geometry_msgs.msg import Point, Point32, PolygonStamped
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import Float32, Header
from visualization_msgs.msg import Marker, MarkerArray

from iwrl6432_ros.free_space import (
    bin_angles, contour_segments, corridor_candidates, free_space_boundary,
    interpolate_short_gaps, make_occupancy, merge_history, nearest_ranges,
)
from iwrl6432_ros.manual_pose_mapping import rotate_translate_3d


class RadarFreeSpace:
    def __init__(self):
        gp = rospy.get_param
        self.frame_id = str(gp("~frame_id", "base_link"))
        self.min_range, self.max_range = float(gp("~min_range_m", 0.2)), float(gp("~max_range_m", 3.0))
        self.min_snr = float(gp("~min_snr_db", 12.0))
        self.min_z, self.max_z = float(gp("~min_z_m", -0.3)), float(gp("~max_z_m", 0.8))
        self.min_angle, self.max_angle = float(gp("~min_angle_deg", -60.0)), float(gp("~max_angle_deg", 60.0))
        self.angle_bin = float(gp("~angle_bin_deg", 3.0))
        self.history = deque(maxlen=int(gp("~history_frames", 5)))
        self.max_jump = float(gp("~max_contour_jump_m", 0.6))
        self.max_gap = int(gp("~max_interpolation_gap_bins", 2))
        self.safety_margin = float(gp("~safety_margin_m", 0.25))
        self.unknown_range = float(gp("~unknown_free_range_m", 0.5))
        self.resolution = float(gp("~resolution_m", 0.05))
        self.grid_width, self.grid_height = float(gp("~grid_width_m", 6.0)), float(gp("~grid_height_m", 6.0))
        self.thickness = float(gp("~occupancy_thickness_m", 0.15))
        self.inflation = float(gp("~inflation_radius_m", 0.25))
        self.min_clearance = float(gp("~min_clearance_m", 1.0))
        self.robot_width = float(gp("~robot_width_m", 0.35))
        self.clearance_margin = float(gp("~clearance_margin_m", 0.15))
        self.min_corridor_angle = float(gp("~min_corridor_angle_deg", 15.0))
        if not (0 < self.min_range < self.max_range and self.min_z <= self.max_z and
                self.min_angle < self.max_angle and self.angle_bin > 0 and self.history.maxlen > 0 and
                self.resolution > 0 and self.grid_width > 0 and self.grid_height > 0):
            raise ValueError("invalid radar free-space parameters")
        self.angles = bin_angles(self.min_angle, self.max_angle, self.angle_bin)
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.contour_pub = rospy.Publisher("/radar/obstacle_contour", Marker, queue_size=1)
        self.free_pub = rospy.Publisher("/radar/free_space", PolygonStamped, queue_size=1)
        self.grid_pub = rospy.Publisher("/radar/local_occupancy", OccupancyGrid, queue_size=1)
        self.corridor_pub = rospy.Publisher("/radar/traversable_markers", MarkerArray, queue_size=1)
        self.heading_pub = rospy.Publisher("/radar/recommended_heading", Float32, queue_size=1)
        self.sub = rospy.Subscriber("/radar/points", PointCloud2, self.callback, queue_size=10)

    def transformed_points(self, cloud):
        names = {field.name for field in cloud.fields}
        if not {"x", "y", "z", "snr"}.issubset(names):
            rospy.logwarn_throttle(5.0, "Free-space input lacks x/y/z/snr fields")
            return None
        transform = None
        if cloud.header.frame_id != self.frame_id:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.frame_id, cloud.header.frame_id, cloud.header.stamp, rospy.Duration(0.1)).transform
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as exc:
                rospy.logwarn_throttle(2.0, "Free-space TF unavailable: %s", exc)
                return None
        output = []
        for x_value, y_value, z_value, snr in pc2.read_points(
                cloud, field_names=("x", "y", "z", "snr"), skip_nans=True):
            if transform is not None:
                point = rotate_translate_3d(
                    (x_value, y_value, z_value),
                    (transform.translation.x, transform.translation.y, transform.translation.z),
                    (transform.rotation.x, transform.rotation.y, transform.rotation.z, transform.rotation.w))
            else:
                point = (x_value, y_value, z_value)
            output.append(point + (snr,))
        return output

    def callback(self, cloud):
        points = self.transformed_points(cloud)
        if points is None:
            return
        self.history.append(nearest_ranges(
            points, self.min_range, self.max_range, self.min_angle, self.max_angle,
            self.angle_bin, self.min_snr, self.min_z, self.max_z))
        measured = merge_history(self.history)
        interpolated = interpolate_short_gaps(measured, self.max_gap, self.max_jump)
        stamp = cloud.header.stamp if cloud.header.stamp != rospy.Time() else rospy.Time.now()
        self.publish_contour(interpolated, stamp)
        self.publish_polygon(interpolated, stamp)
        self.publish_grid(measured, stamp)
        candidates = corridor_candidates(
            interpolated, self.angles, self.angle_bin, self.min_clearance,
            self.robot_width, self.clearance_margin, self.min_corridor_angle)
        self.publish_corridors(candidates, stamp)
        self.heading_pub.publish(Float32(candidates[0]["center_angle_deg"] if candidates else float("nan")))

    def base_marker(self, marker_id, marker_type, stamp, namespace):
        marker = Marker(header=Header(stamp=stamp, frame_id=self.frame_id), ns=namespace,
                        id=marker_id, type=marker_type, action=Marker.ADD)
        marker.pose.orientation.w = 1.0
        marker.lifetime = rospy.Duration(0.6)
        return marker

    def publish_contour(self, ranges, stamp):
        marker = self.base_marker(0, Marker.LINE_LIST, stamp, "obstacle_contour")
        marker.scale.x = 0.055
        marker.color.r, marker.color.g, marker.color.b, marker.color.a = 1.0, 0.25, 0.05, 1.0
        for segment in contour_segments(ranges, self.angles, self.max_jump):
            marker.points.extend(Point(x=p[0], y=p[1], z=0.05) for p in segment)
        self.contour_pub.publish(marker)

    def publish_polygon(self, ranges, stamp):
        polygon = PolygonStamped(header=Header(stamp=stamp, frame_id=self.frame_id))
        # Reverse the ascending-angle bins so the polygon runs left (+angle)
        # to right (-angle), then closes at the sensor origin.
        boundary = free_space_boundary(ranges, self.angles, self.safety_margin,
                                       self.unknown_range)
        polygon.polygon.points = [Point32(x=x, y=y, z=0.0)
                                  for x, y in reversed(boundary)]
        polygon.polygon.points.append(Point32(x=0.0, y=0.0, z=0.0))
        self.free_pub.publish(polygon)

    def publish_grid(self, ranges, stamp):
        width, height, origin_x, origin_y, data = make_occupancy(
            ranges, self.angles, self.resolution, self.grid_width, self.grid_height,
            0.0, 0.0, self.thickness, self.inflation)
        grid = OccupancyGrid(header=Header(stamp=stamp, frame_id=self.frame_id))
        grid.info.map_load_time = stamp
        grid.info.resolution, grid.info.width, grid.info.height = self.resolution, width, height
        grid.info.origin.position.x, grid.info.origin.position.y = origin_x, origin_y
        grid.info.origin.orientation.w = 1.0
        grid.data = data
        self.grid_pub.publish(grid)

    def publish_corridors(self, candidates, stamp):
        array = MarkerArray()
        clear = self.base_marker(0, Marker.DELETEALL, stamp, "traversable")
        array.markers.append(clear)
        for index, candidate in enumerate(candidates):
            marker = self.base_marker(index + 1, Marker.TRIANGLE_LIST, stamp, "traversable")
            marker.color.r, marker.color.g, marker.color.b, marker.color.a = 0.1, 0.9, 0.25, 0.25
            radius = max(0.0, candidate["min_distance_m"] - self.safety_margin)
            left, right = math.radians(candidate["start_angle_deg"]), math.radians(candidate["end_angle_deg"])
            marker.points = [Point(0.0, 0.0, 0.03),
                             Point(radius * math.cos(left), radius * math.sin(left), 0.03),
                             Point(radius * math.cos(right), radius * math.sin(right), 0.03)]
            array.markers.append(marker)
        if candidates:
            best = candidates[0]
            arrow = self.base_marker(1000, Marker.ARROW, stamp, "recommended_heading")
            angle = math.radians(best["center_angle_deg"])
            length = min(1.5, best["min_distance_m"] - self.safety_margin)
            arrow.points = [Point(0.0, 0.0, 0.12),
                            Point(length * math.cos(angle), length * math.sin(angle), 0.12)]
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.07, 0.14, 0.18
            arrow.color.r, arrow.color.g, arrow.color.b, arrow.color.a = 0.1, 0.45, 1.0, 1.0
            array.markers.append(arrow)
        self.corridor_pub.publish(array)


if __name__ == "__main__":
    rospy.init_node("radar_free_space")
    RadarFreeSpace()
    rospy.spin()
