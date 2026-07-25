#!/usr/bin/env python3
"""Publish a latched wireframe for the IWRL6432 3D field of view."""

import math

import rospy
from geometry_msgs.msg import Point
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray


def spherical_point(radius, azimuth_deg, elevation_deg):
    """Radar axes: +Y front, -X left, +X right, +Z up.

    Positive azimuth turns from front toward physical radar left.
    """
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    horizontal = radius * math.cos(elevation)
    return Point(x=-horizontal * math.sin(azimuth),
                 y=horizontal * math.cos(azimuth),
                 z=radius * math.sin(elevation))


class Radar3DFovGuides:
    def __init__(self):
        self.frame_id = str(rospy.get_param("~frame_id", "radar_link"))
        self.max_range = float(rospy.get_param("~max_range_m", 3.0))
        self.horizontal_half_fov = float(rospy.get_param("~horizontal_half_fov_deg", 60.0))
        self.min_elevation = float(rospy.get_param("~min_elevation_deg", -10.0))
        self.max_elevation = float(rospy.get_param("~max_elevation_deg", 60.0))
        self.publisher = rospy.Publisher(
            "/radar/rviz_guides_3d", MarkerArray, queue_size=1, latch=True)
        rospy.sleep(0.2)
        self.publisher.publish(self.build_markers())

    def marker(self, marker_id, marker_type, color, width=0.012):
        marker = Marker()
        marker.header.frame_id = self.frame_id
        marker.header.stamp = rospy.Time.now()
        marker.ns = "radar_3d_fov"
        marker.id = marker_id
        marker.type = marker_type
        marker.action = Marker.ADD
        marker.pose.orientation.w = 1.0
        marker.scale.x = width
        marker.color = color
        marker.lifetime = rospy.Duration(0)
        return marker

    def arrow(self, marker_id, end, color):
        marker = self.marker(marker_id, Marker.ARROW, color)
        marker.points = [Point(0.0, 0.0, 0.0), end]
        marker.scale.x = 0.035 if marker_id == 100 else 0.022
        marker.scale.y = 0.09 if marker_id == 100 else 0.06
        marker.scale.z = 0.14 if marker_id == 100 else 0.10
        return marker

    def text(self, marker_id, position, label, color, size=0.14):
        marker = self.marker(marker_id, Marker.TEXT_VIEW_FACING, color)
        marker.pose.position = position
        marker.scale.z = size
        marker.text = label
        return marker

    def build_markers(self):
        array = MarkerArray()
        boundary_color = ColorRGBA(0.2, 0.75, 1.0, 0.38)
        range_color = ColorRGBA(0.35, 0.9, 0.7, 0.24)

        rays = self.marker(0, Marker.LINE_LIST, boundary_color, 0.018)
        origin = Point(0.0, 0.0, 0.0)
        for azimuth in (-self.horizontal_half_fov, self.horizontal_half_fov):
            for elevation in (self.min_elevation, self.max_elevation):
                rays.points.extend([origin, spherical_point(self.max_range, azimuth, elevation)])
        array.markers.append(rays)

        marker_id = 1
        azimuth_steps = 60
        azimuths = [
            -self.horizontal_half_fov + index * 2.0 * self.horizontal_half_fov / azimuth_steps
            for index in range(azimuth_steps + 1)]
        for radius in (1.0, 2.0, 3.0):
            if radius > self.max_range + 1e-9:
                continue
            arc = self.marker(marker_id, Marker.LINE_STRIP, range_color)
            arc.points = [spherical_point(radius, degree, 0.0) for degree in azimuths]
            array.markers.append(arc)
            marker_id += 1

        for elevation in (self.min_elevation, self.max_elevation):
            edge = self.marker(marker_id, Marker.LINE_STRIP, boundary_color)
            edge.points = [spherical_point(self.max_range, degree, elevation)
                           for degree in azimuths]
            array.markers.append(edge)
            marker_id += 1
        for azimuth in (-self.horizontal_half_fov, self.horizontal_half_fov):
            edge = self.marker(marker_id, Marker.LINE_STRIP, boundary_color)
            steps = 70
            edge.points = [spherical_point(
                self.max_range, azimuth,
                self.min_elevation + index * (self.max_elevation - self.min_elevation) / steps)
                for index in range(steps + 1)]
            array.markers.append(edge)
            marker_id += 1

        # Fixed IDs make the latched MarkerArray update without DELETEALL or flicker.
        front_color = ColorRGBA(1.0, 0.22, 0.08, 0.95)
        lateral_color = ColorRGBA(0.25, 0.9, 0.35, 0.9)
        up_color = ColorRGBA(0.25, 0.5, 1.0, 0.95)
        origin_color = ColorRGBA(1.0, 0.9, 0.2, 0.95)
        array.markers.extend([
            self.arrow(100, Point(0.0, 1.0, 0.0), front_color),
            self.text(101, Point(0.0, 1.18, 0.10), "RADAR FRONT", front_color, 0.17),
            self.arrow(102, Point(-0.7, 0.0, 0.0), lateral_color),
            self.text(103, Point(-0.84, 0.0, 0.08), "LEFT", lateral_color),
            self.arrow(104, Point(0.7, 0.0, 0.0), lateral_color),
            self.text(105, Point(0.84, 0.0, 0.08), "RIGHT", lateral_color),
            self.arrow(106, Point(0.0, 0.0, 0.7), up_color),
            self.text(107, Point(0.0, 0.0, 0.86), "UP", up_color),
        ])
        origin = self.marker(108, Marker.SPHERE, origin_color)
        origin.scale.x = origin.scale.y = origin.scale.z = 0.10
        array.markers.append(origin)
        array.markers.append(self.text(
            109, Point(0.0, -0.16, 0.13), "SENSOR ORIGIN", origin_color, 0.13))
        return array


def main():
    rospy.init_node("radar_3d_fov_guides")
    Radar3DFovGuides()
    rospy.spin()


if __name__ == "__main__":
    main()
