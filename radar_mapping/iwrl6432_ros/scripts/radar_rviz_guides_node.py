#!/usr/bin/env python3
"""Publish static RViz guides for interpreting radar range and direction."""

import math

import rospy
from geometry_msgs.msg import Point
from visualization_msgs.msg import Marker, MarkerArray


class RadarRvizGuides:
    def __init__(self):
        self.frame_id = rospy.get_param("~frame_id", "base_link")
        self.max_range = float(rospy.get_param("~max_range", 3.0))
        self.ring_interval = float(rospy.get_param("~ring_interval", 0.5))
        self.fov_deg = float(rospy.get_param("~fov_deg", 90.0))
        self.publish_rate = float(rospy.get_param("~publish_rate", 1.0))
        self.show_labels = bool(rospy.get_param("~show_labels", True))
        if self.max_range <= 0.0 or self.ring_interval <= 0.0:
            raise ValueError("max_range and ring_interval must be positive")
        if self.publish_rate <= 0.0:
            raise ValueError("publish_rate must be positive")
        self.publisher = rospy.Publisher(
            "/radar/rviz_guides", MarkerArray, queue_size=1, latch=True
        )

    def marker(self, namespace, marker_id, marker_type, color):
        item = Marker()
        item.header.frame_id = self.frame_id
        item.header.stamp = rospy.Time.now()
        item.ns = namespace
        item.id = marker_id
        item.type = marker_type
        item.action = Marker.ADD
        item.pose.orientation.w = 1.0
        item.color.r, item.color.g, item.color.b, item.color.a = color
        return item

    @staticmethod
    def point(x, y, z=0.02):
        return Point(x=x, y=y, z=z)

    def build(self):
        markers = []

        zones = (
            (0, 0.0, 1.0, "COLLISION RISK", 0.55, (0.85, 0.12, 0.10, 0.25)),
            (1, 1.0, 2.0, "SLOW / AVOID", 1.45, (0.95, 0.60, 0.08, 0.20)),
            (2, 2.0, 3.0, "PATH PLANNING", 2.45, (0.10, 0.65, 0.48, 0.15)),
        )
        for marker_id, inner, outer, text, text_x, color in zones:
            sector = self.marker("risk_zones", marker_id, Marker.TRIANGLE_LIST, color)
            for index in range(72):
                angle0 = -math.pi/2.0 + math.pi*index/72.0
                angle1 = -math.pi/2.0 + math.pi*(index + 1)/72.0
                inner0 = self.point(inner*math.cos(angle0), inner*math.sin(angle0), 0.005)
                inner1 = self.point(inner*math.cos(angle1), inner*math.sin(angle1), 0.005)
                outer0 = self.point(outer*math.cos(angle0), outer*math.sin(angle0), 0.005)
                outer1 = self.point(outer*math.cos(angle1), outer*math.sin(angle1), 0.005)
                sector.points.extend((inner0, outer0, outer1, inner0, outer1, inner1))
            markers.append(sector)
            if self.show_labels:
                zone_label = self.marker("risk_labels", marker_id,
                                         Marker.TEXT_VIEW_FACING,
                                         (0.95, 0.95, 0.95, 1.0))
                zone_label.pose.position = self.point(text_x, -0.25, 0.12)
                zone_label.scale.z = 0.11
                zone_label.text = text
                markers.append(zone_label)

        origin = self.marker("origin", 0, Marker.SPHERE, (0.95, 0.85, 0.25, 1.0))
        origin.pose.position.z = 0.06
        origin.scale.x = origin.scale.y = origin.scale.z = 0.16
        markers.append(origin)

        origin_label = self.marker("origin_label", 0, Marker.TEXT_VIEW_FACING,
                                   (1.0, 1.0, 1.0, 1.0))
        origin_label.pose.position = self.point(0.0, -0.18, 0.14)
        origin_label.scale.z = 0.16
        origin_label.text = "SENSOR ORIGIN"
        markers.append(origin_label)

        directions = (
            (0, "front", 1.0, 0.0, "FRONT +X", (0.90, 0.20, 0.20, 1.0)),
            (1, "left", 0.0, 1.0, "LEFT +Y", (0.20, 0.80, 0.30, 1.0)),
            (2, "right", 0.0, -1.0, "RIGHT -Y", (0.25, 0.65, 0.30, 1.0)),
        )
        for marker_id, name, x, y, text, color in directions:
            arrow = self.marker("direction_arrows", marker_id, Marker.ARROW, color)
            arrow.points = [self.point(0.0, 0.0, 0.06), self.point(x, y, 0.06)]
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.06, 0.14, 0.18
            markers.append(arrow)
            label = self.marker("direction_labels", marker_id, Marker.TEXT_VIEW_FACING,
                                (1.0, 1.0, 1.0, 1.0))
            if name == "front":
                label.pose.position = self.point(0.70, 0.32, 0.18)
            else:
                label.pose.position = self.point(1.18*x, 1.18*y, 0.18)
            label.scale.z = 0.18
            label.text = text
            markers.append(label)

        ring_count = int(math.floor(self.max_range / self.ring_interval + 1e-9))
        for index in range(1, ring_count + 1):
            radius = index * self.ring_interval
            ring = self.marker("range_rings", index, Marker.LINE_STRIP,
                               (0.40, 0.78, 0.78, 1.0))
            ring.scale.x = 0.025
            ring.points = [
                self.point(radius * math.cos(-math.pi/2.0 + math.pi*i/72.0),
                           radius * math.sin(-math.pi/2.0 + math.pi*i/72.0))
                for i in range(73)
            ]
            markers.append(ring)
            if self.show_labels:
                label = self.marker("range_labels", index, Marker.TEXT_VIEW_FACING,
                                    (0.95, 0.95, 0.95, 1.0))
                label.pose.position = self.point(radius, 0.0, 0.15)
                label.scale.z = 0.12
                label.text = "%.1f m" % radius
                markers.append(label)

        center = self.marker("centerline", 0, Marker.LINE_STRIP,
                             (0.90, 0.30, 0.30, 1.0))
        center.scale.x = 0.035
        center.points = [self.point(0.0, 0.0), self.point(self.max_range, 0.0)]
        markers.append(center)

        for marker_id, angle_deg in enumerate((self.fov_deg, -self.fov_deg)):
            angle = math.radians(angle_deg)
            boundary = self.marker("fov_boundaries", marker_id, Marker.LINE_STRIP,
                                   (0.85, 0.75, 0.30, 1.0))
            boundary.scale.x = 0.035
            boundary.points = [
                self.point(0.0, 0.0),
                self.point(self.max_range*math.cos(angle),
                           self.max_range*math.sin(angle)),
            ]
            markers.append(boundary)
        return MarkerArray(markers=markers)

    def run(self):
        rate = rospy.Rate(self.publish_rate)
        while not rospy.is_shutdown():
            self.publisher.publish(self.build())
            rate.sleep()


if __name__ == "__main__":
    rospy.init_node("radar_rviz_guides")
    RadarRvizGuides().run()
