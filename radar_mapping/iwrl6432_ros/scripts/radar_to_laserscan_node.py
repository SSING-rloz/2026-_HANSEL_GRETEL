#!/usr/bin/env python3
"""Convert sparse IWRL6432 PointCloud2 frames to a temporal LaserScan."""

from collections import deque
import math

import rospy
from sensor_msgs import point_cloud2
from sensor_msgs.msg import LaserScan, PointCloud2


class RadarToLaserScan:
    AXES = {"x": 0, "y": 1, "z": 2}

    def __init__(self):
        self.input_topic = rospy.get_param("~input_topic", "/radar/points")
        self.output_topic = rospy.get_param("~output_topic", "/radar/scan")
        self.output_frame = rospy.get_param("~output_frame", "base_link")
        self.angle_min = float(rospy.get_param("~angle_min", -1.396))
        self.angle_max = float(rospy.get_param("~angle_max", 1.396))
        self.angle_increment = float(
            rospy.get_param("~angle_increment", math.pi / 180.0)
        )
        self.range_min = float(rospy.get_param("~range_min", 0.25))
        self.range_max = float(rospy.get_param("~range_max", 7.5))
        self.z_min = float(rospy.get_param("~z_min", -0.5))
        self.z_max = float(rospy.get_param("~z_max", 0.5))
        self.min_snr = float(rospy.get_param("~min_snr", 15.0))
        self.temporal_window = max(1, int(rospy.get_param("~temporal_window", 3)))

        # Configurable candidate mapping. TI calls these sensor coordinates but
        # the local SDK text does not fully specify physical axis directions.
        self.axis_sources = (
            rospy.get_param("~ros_x_from", "y"),
            rospy.get_param("~ros_y_from", "x"),
            rospy.get_param("~ros_z_from", "z"),
        )
        self.axis_signs = (
            float(rospy.get_param("~ros_x_sign", 1.0)),
            float(rospy.get_param("~ros_y_sign", -1.0)),
            float(rospy.get_param("~ros_z_sign", 1.0)),
        )
        if any(source not in self.AXES for source in self.axis_sources):
            raise ValueError("ros_*_from must be one of x, y, z")
        if self.angle_increment <= 0 or self.angle_max <= self.angle_min:
            raise ValueError("invalid LaserScan angle parameters")
        if self.range_max <= self.range_min:
            raise ValueError("range_max must be greater than range_min")

        self.frames = deque(maxlen=self.temporal_window)
        self.last_stamp = None
        self.publisher = rospy.Publisher(self.output_topic, LaserScan, queue_size=10)
        self.subscriber = rospy.Subscriber(
            self.input_topic, PointCloud2, self.callback, queue_size=10
        )
        rospy.loginfo(
            "Radar axis candidate: ROS x=%g*radar_%s, y=%g*radar_%s, "
            "z=%g*radar_%s; temporal_window=%d",
            self.axis_signs[0], self.axis_sources[0],
            self.axis_signs[1], self.axis_sources[1],
            self.axis_signs[2], self.axis_sources[2], self.temporal_window,
        )

    def transform_xyz(self, x, y, z):
        radar = (x, y, z)
        return tuple(
            sign * radar[self.AXES[source]]
            for source, sign in zip(self.axis_sources, self.axis_signs)
        )

    def callback(self, cloud):
        current = []
        fields = ("x", "y", "z", "snr")
        for x, y, z, snr in point_cloud2.read_points(
                cloud, field_names=fields, skip_nans=True):
            ros_x, ros_y, ros_z = self.transform_xyz(x, y, z)
            planar_range = math.hypot(ros_x, ros_y)
            if (snr >= self.min_snr and self.z_min <= ros_z <= self.z_max and
                    self.range_min <= planar_range <= self.range_max):
                current.append((ros_x, ros_y, planar_range))
        self.frames.append(current)

        bin_count = int(math.floor(
            (self.angle_max - self.angle_min) / self.angle_increment
        )) + 1
        ranges = [math.inf] * bin_count
        for frame in self.frames:
            for x, y, distance in frame:
                angle = math.atan2(y, x)
                if self.angle_min <= angle <= self.angle_max:
                    index = int(math.floor(
                        (angle - self.angle_min) / self.angle_increment
                    ))
                    index = min(index, bin_count - 1)
                    if distance < ranges[index]:
                        ranges[index] = distance

        scan = LaserScan()
        scan.header.stamp = cloud.header.stamp if cloud.header.stamp else rospy.Time.now()
        scan.header.frame_id = self.output_frame
        scan.angle_min = self.angle_min
        scan.angle_max = self.angle_min + (bin_count - 1) * self.angle_increment
        scan.angle_increment = self.angle_increment
        scan.time_increment = 0.0
        if self.last_stamp is None:
            scan.scan_time = 0.0
        else:
            scan.scan_time = max(0.0, (scan.header.stamp - self.last_stamp).to_sec())
        self.last_stamp = scan.header.stamp
        scan.range_min = self.range_min
        scan.range_max = self.range_max
        scan.ranges = ranges
        scan.intensities = []
        self.publisher.publish(scan)


if __name__ == "__main__":
    rospy.init_node("radar_to_laserscan")
    RadarToLaserScan()
    rospy.spin()
