#!/usr/bin/env python3
"""Publish one manual radar Pose2D; angles are degrees by default."""

import argparse
import math
import time

import rospy
from geometry_msgs.msg import Pose2D


def arguments():
    parser = argparse.ArgumentParser(
        description="Publish /radar/manual_pose (angle defaults to degrees)"
    )
    parser.add_argument("x", type=float, help="map X position in metres")
    parser.add_argument("y", type=float, help="map Y position in metres")
    parser.add_argument("yaw", type=float, help="yaw angle")
    units = parser.add_mutually_exclusive_group()
    units.add_argument("--degrees", action="store_true",
                       help="interpret yaw as degrees (default)")
    units.add_argument("--radians", action="store_true",
                       help="interpret yaw as radians")
    return parser.parse_args(rospy.myargv()[1:])


if __name__ == "__main__":
    args = arguments()
    yaw = args.yaw if args.radians else math.radians(args.yaw)
    rospy.init_node("publish_manual_radar_pose", anonymous=True)
    publisher = rospy.Publisher("/radar/manual_pose", Pose2D, queue_size=1, latch=True)
    message = Pose2D(x=args.x, y=args.y, theta=yaw)
    deadline = time.monotonic() + 2.0
    while publisher.get_num_connections() == 0 and time.monotonic() < deadline:
        rospy.sleep(0.05)
    publisher.publish(message)
    rospy.sleep(0.5)
    rospy.loginfo("Published manual pose x=%.3f y=%.3f yaw=%.3f rad",
                  message.x, message.y, message.theta)
