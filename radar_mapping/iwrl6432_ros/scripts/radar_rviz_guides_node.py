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
        self.show_front_arrow = bool(rospy.get_param("~show_front_arrow", True))
        self.show_fov_boundaries = bool(rospy.get_param(
            "~show_fov_boundaries", True))
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

        # Presentation view: one subtle forward cue, with no persistent risk-zone
        # labels or side/origin annotations competing with live obstacle markers.
        if getattr(self, "show_front_arrow", True):
            front = self.marker("direction_arrows", 0, Marker.ARROW,
                                (0.70, 0.72, 0.75, 0.55))
            front.points = [self.point(0.0, 0.0, 0.025),
                            self.point(self.max_range, 0.0, 0.025)]
            front.scale.x, front.scale.y, front.scale.z = 0.010, 0.028, 0.035
            markers.append(front)
        front_label = self.marker("direction_labels", 0, Marker.TEXT_VIEW_FACING,
                                  (0.74, 0.77, 0.80, 0.72))
        front_label.pose.position = self.point(
            self.max_range + 0.045, 0.24, 0.075)
        front_label.scale.z = 0.032
        front_label.text = "FRONT"
        markers.append(front_label)

        ring_count = int(math.floor(self.max_range / self.ring_interval + 1e-9))
        for index in range(1, ring_count + 1):
            radius = index * self.ring_interval
            ring = self.marker("range_rings", index, Marker.LINE_STRIP,
                               (0.62, 0.65, 0.68, 0.24))
            ring.scale.x = 0.0035
            half_fov = math.radians(self.fov_deg)
            ring.points = [
                self.point(radius * math.cos(-half_fov + 2.0*half_fov*i/72.0),
                           radius * math.sin(-half_fov + 2.0*half_fov*i/72.0),
                           0.0)
                for i in range(73)
            ]
            markers.append(ring)
            if self.show_labels:
                label = self.marker("range_labels", index, Marker.TEXT_VIEW_FACING,
                                    (0.70, 0.73, 0.76, 0.68))
                label.pose.position = self.point(radius, -0.026, 0.052)
                label.scale.z = 0.024
                label.text = "%.1f m" % radius
                markers.append(label)

        if getattr(self, "show_fov_boundaries", True):
            for marker_id, angle_deg in enumerate((self.fov_deg, -self.fov_deg)):
                angle = math.radians(angle_deg)
                boundary = self.marker("fov_boundaries", marker_id, Marker.LINE_STRIP,
                                       (0.68, 0.70, 0.72, 0.28))
                boundary.scale.x = 0.006
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
