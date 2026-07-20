#!/usr/bin/env python3
"""Accumulate radar points in map using user-supplied Pose2D poses."""

import collections
import math
import threading

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from geometry_msgs.msg import Pose2D, TransformStamped
from sensor_msgs.msg import PointCloud2, PointField
from std_srvs.srv import Empty, EmptyResponse

from iwrl6432_ros.manual_pose_mapping import (
    rotate_translate_3d, transform_xy, voxel_key,
)


FIELDS = [
    PointField(name=name, offset=index*4, datatype=PointField.FLOAT32, count=1)
    for index, name in enumerate(("x", "y", "z", "doppler", "snr", "noise"))
]


class ManualPoseMapper:
    def __init__(self):
        self.input_topic = rospy.get_param("~input_topic", "/radar/points")
        self.output_topic = rospy.get_param("~output_topic", "/radar/map_points")
        self.map_frame = rospy.get_param("~map_frame", "map")
        self.pose_frame = rospy.get_param("~pose_frame", "base_link")
        self.max_points = int(rospy.get_param("~max_points", 100000))
        self.voxel_size = float(rospy.get_param("~voxel_size", 0.05))
        self.min_snr = float(rospy.get_param("~min_snr", 15.0))
        self.min_range = float(rospy.get_param("~min_range", 0.2))
        self.max_range = float(rospy.get_param("~max_range", 3.0))
        self.z_min = float(rospy.get_param("~z_min", -0.5))
        self.z_max = float(rospy.get_param("~z_max", 0.5))
        if self.max_points <= 0:
            raise ValueError("max_points must be positive")
        if self.voxel_size < 0.0:
            raise ValueError("voxel_size must be non-negative; use 0 to disable")
        if self.map_frame == self.pose_frame:
            raise ValueError("map_frame and pose_frame must differ")

        self.lock = threading.Lock()
        self.pose = None
        self.raw_points = collections.deque(maxlen=self.max_points)
        self.voxels = collections.OrderedDict()
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(10.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.tf_broadcaster = tf2_ros.TransformBroadcaster()
        self.map_publisher = rospy.Publisher(
            self.output_topic, PointCloud2, queue_size=1, latch=True
        )
        self.pose_publisher = rospy.Publisher(
            "/radar/current_pose", Pose2D, queue_size=1, latch=True
        )
        self.pose_subscriber = rospy.Subscriber(
            "/radar/manual_pose", Pose2D, self.pose_callback, queue_size=1
        )
        self.cloud_subscriber = rospy.Subscriber(
            self.input_topic, PointCloud2, self.cloud_callback, queue_size=5
        )
        self.clear_service = rospy.Service(
            "/radar/clear_map", Empty, self.clear_callback
        )
        self.tf_timer = rospy.Timer(rospy.Duration(0.1), self.broadcast_pose)
        rospy.on_shutdown(self.shutdown)

    def pose_callback(self, message):
        with self.lock:
            self.pose = (float(message.x), float(message.y), float(message.theta))
        self.pose_publisher.publish(message)
        self.broadcast_pose()
        rospy.loginfo("Manual radar pose: x=%.3f y=%.3f yaw=%.3f rad",
                      message.x, message.y, message.theta)

    def broadcast_pose(self, _event=None):
        with self.lock:
            pose = self.pose
        if pose is None:
            return
        transform = TransformStamped()
        transform.header.stamp = rospy.Time.now()
        transform.header.frame_id = self.map_frame
        transform.child_frame_id = self.pose_frame
        transform.transform.translation.x = pose[0]
        transform.transform.translation.y = pose[1]
        transform.transform.rotation.z = math.sin(pose[2]/2.0)
        transform.transform.rotation.w = math.cos(pose[2]/2.0)
        self.tf_broadcaster.sendTransform(transform)

    def input_to_pose_transform(self, cloud):
        source = cloud.header.frame_id
        if source == self.pose_frame:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)
        transform = self.tf_buffer.lookup_transform(
            self.pose_frame, source, rospy.Time(0), rospy.Duration(0.2)
        ).transform
        return (
            (transform.translation.x, transform.translation.y,
             transform.translation.z),
            (transform.rotation.x, transform.rotation.y,
             transform.rotation.z, transform.rotation.w),
        )

    def cloud_callback(self, cloud):
        with self.lock:
            pose = self.pose
        if pose is None:
            rospy.logwarn_throttle(5.0, "No /radar/manual_pose yet; not accumulating")
            return
        available = {field.name for field in cloud.fields}
        required = {"x", "y", "z", "doppler", "snr", "noise"}
        if not required.issubset(available):
            rospy.logerr_throttle(5.0, "PointCloud2 lacks required fields: %s",
                                  sorted(required - available))
            return
        try:
            translation, quaternion = self.input_to_pose_transform(cloud)
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as exc:
            rospy.logwarn_throttle(5.0, "Cannot transform %s to %s: %s",
                                   cloud.header.frame_id, self.pose_frame, exc)
            return

        additions = []
        names = ("x", "y", "z", "doppler", "snr", "noise")
        for point in pc2.read_points(cloud, field_names=names, skip_nans=True):
            base_x, base_y, base_z = rotate_translate_3d(
                point[:3], translation, quaternion
            )
            distance = math.sqrt(base_x*base_x + base_y*base_y + base_z*base_z)
            if not (point[4] >= self.min_snr and
                    self.min_range <= distance <= self.max_range and
                    self.z_min <= base_z <= self.z_max):
                continue
            map_x, map_y = transform_xy(base_x, base_y, *pose)
            additions.append((map_x, map_y, base_z, point[3], point[4], point[5]))

        with self.lock:
            if self.voxel_size > 0.0:
                for point in additions:
                    key = voxel_key(point, self.voxel_size)
                    self.voxels[key] = point
                    self.voxels.move_to_end(key)
                while len(self.voxels) > self.max_points:
                    self.voxels.popitem(last=False)
                snapshot = list(self.voxels.values())
            else:
                self.raw_points.extend(additions)
                snapshot = list(self.raw_points)
        self.publish_map(snapshot)
        rospy.loginfo_throttle(2.0, "Accumulated radar map: %d points", len(snapshot))

    def publish_map(self, points):
        header = cloud_header(self.map_frame)
        self.map_publisher.publish(pc2.create_cloud(header, FIELDS, points))

    def clear_callback(self, _request):
        with self.lock:
            self.raw_points.clear()
            self.voxels.clear()
        self.publish_map([])
        rospy.loginfo("Accumulated radar map cleared")
        return EmptyResponse()

    @staticmethod
    def shutdown():
        rospy.loginfo("Manual pose mapping node stopped")


def cloud_header(frame_id):
    from std_msgs.msg import Header
    return Header(stamp=rospy.Time.now(), frame_id=frame_id)


if __name__ == "__main__":
    rospy.init_node("manual_pose_mapping")
    ManualPoseMapper()
    rospy.spin()
