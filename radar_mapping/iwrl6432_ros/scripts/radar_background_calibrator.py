#!/usr/bin/env python3
"""Measure a fixed-scene 3D voxel background profile from /radar/points."""

import csv
import math
import os
import threading
import time

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
import yaml

from sensor_msgs.msg import PointCloud2

from iwrl6432_ros.manual_pose_mapping import rotate_translate_3d
from iwrl6432_ros.sector_occupancy import (
    POINT_FIELDS, build_background_profile, profile_document,
    valid_near_field_point,
)


class RadarBackgroundCalibrator:
    def __init__(self):
        gp = rospy.get_param
        self.input_topic = str(gp("~input_topic", "/radar/points"))
        self.frame_id = str(gp("~frame_id", "base_link"))
        self.duration_sec = float(gp("~duration_sec", 10.0))
        self.min_range = float(gp("~valid_min_range_m", 0.10))
        self.max_range = float(gp("~max_range_m", 1.00))
        self.min_snr = float(gp("~min_snr_db", 8.0))
        self.half_fov = 0.5 * float(gp("~front_fov_deg", 120.0))
        self.voxel_size = float(gp("~background_voxel_size_m", 0.02))
        self.minimum_presence = float(gp("~background_min_presence_ratio", 0.90))
        self.output_directory = os.path.expanduser(str(gp(
            "~output_directory", "/tmp/iwrl6432_sector_occupancy")))
        if not (self.duration_sec > 0 and 0 < self.min_range < self.max_range and
                self.min_snr >= 0 and 0 < self.half_fov <= 90 and
                self.voxel_size > 0 and 0 < self.minimum_presence <= 1):
            raise ValueError("invalid background calibration parameters")
        self.frames = []
        self.received_frames = 0
        self.tf_failures = 0
        self.first_stamp = None
        self.last_stamp = None
        self.lock = threading.Lock()
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(20.0))
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.subscriber = None

    def transformed_frame(self, cloud):
        available = {field.name for field in cloud.fields}
        if not {"x", "y", "z"}.issubset(available):
            rospy.logwarn_throttle(2.0, "Background calibration input lacks x/y/z")
            return None
        names = tuple(name for name in POINT_FIELDS if name in available)
        transform = None
        if cloud.header.frame_id != self.frame_id:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.frame_id, cloud.header.frame_id, cloud.header.stamp,
                    rospy.Duration(0.1)).transform
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as exc:
                self.tf_failures += 1
                rospy.logwarn_throttle(2.0, "Background calibration TF unavailable: %s", exc)
                return None
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
                                      self.min_snr, self.half_fov):
                points.append(point)
        return points

    def callback(self, cloud):
        with self.lock:
            self.received_frames += 1
        points = self.transformed_frame(cloud)
        if points is None:
            return
        stamp = cloud.header.stamp.to_sec()
        with self.lock:
            self.frames.append(points)
            self.first_stamp = stamp if self.first_stamp is None else self.first_stamp
            self.last_stamp = stamp

    def measure(self):
        rospy.sleep(0.5)  # Give the TF listener time to receive the static transform.
        self.subscriber = rospy.Subscriber(
            self.input_topic, PointCloud2, self.callback, queue_size=100)
        started = time.monotonic()
        while not rospy.is_shutdown() and time.monotonic() - started < self.duration_sec:
            time.sleep(0.01)
        self.subscriber.unregister()
        if rospy.is_shutdown():
            raise rospy.ROSInterruptException("shutdown during background calibration")
        with self.lock:
            frames = list(self.frames)
        profile = build_background_profile(
            frames, self.voxel_size, self.minimum_presence)
        self.save(frames, profile)
        return profile

    def save(self, frames, profile):
        os.makedirs(self.output_directory, exist_ok=True)
        document = profile_document(profile, self.voxel_size, self.minimum_presence,
                                    len(frames), self.frame_id)
        yaml_path = os.path.join(self.output_directory, "background_profile.yaml")
        csv_path = os.path.join(self.output_directory, "background_profile.csv")
        summary_path = os.path.join(self.output_directory, "background_summary.txt")
        with open(yaml_path, "w", encoding="utf-8") as stream:
            yaml.safe_dump(document, stream, default_flow_style=False, sort_keys=False)
        columns = ("voxel_x", "voxel_y", "voxel_z", "center_x", "center_y", "center_z",
                   "frame_count", "total_frames", "presence_ratio", "point_count",
                   "average_snr", "average_noise", "average_doppler")
        with open(csv_path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for item in profile:
                writer.writerow(dict(zip(columns, (
                    *item["index"], *item["center"], item["frame_count"],
                    item["total_frames"], item["presence_ratio"], item["point_count"],
                    item["average_snr"], item["average_noise"], item["average_doppler"]))))
        span = ((self.last_stamp - self.first_stamp)
                if self.first_stamp is not None and self.last_stamp is not None else float("nan"))
        rate = ((len(frames) - 1) / span if len(frames) > 1 and span > 0 else float("nan"))
        total_points = sum(len(frame) for frame in frames)
        lines = [
            "duration_sec={:.6f}".format(self.duration_sec),
            "received_frames={}".format(self.received_frames),
            "valid_tf_frames={}".format(len(frames)),
            "tf_failures={}".format(self.tf_failures),
            "observed_frame_span_sec={:.6f}".format(span),
            "frequency_hz={:.6f}".format(rate),
            "valid_points={}".format(total_points),
            "average_valid_points_per_frame={:.6f}".format(
                total_points / len(frames) if frames else float("nan")),
            "voxel_size_m={:.6f}".format(self.voxel_size),
            "minimum_presence_ratio={:.6f}".format(self.minimum_presence),
            "registered_voxels={}".format(len(profile)),
        ]
        for item in profile:
            lines.append(
                "voxel={} center=({:.6f},{:.6f},{:.6f}) frames={}/{} ratio={:.6f} "
                "snr={} noise={} doppler={}".format(
                    item["index"], *item["center"], item["frame_count"],
                    item["total_frames"], item["presence_ratio"],
                    item["average_snr"], item["average_noise"], item["average_doppler"]))
        with open(summary_path, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        rospy.loginfo("Background profile: %d voxels from %d frames; saved in %s",
                      len(profile), len(frames), self.output_directory)


def main():
    rospy.init_node("radar_background_calibrator")
    calibrator = RadarBackgroundCalibrator()
    calibrator.measure()


if __name__ == "__main__":
    main()
