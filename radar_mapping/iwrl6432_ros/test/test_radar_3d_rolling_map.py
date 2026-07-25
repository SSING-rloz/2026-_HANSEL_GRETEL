#!/usr/bin/env python3
import math
import os
import sys
import unittest

from geometry_msgs.msg import Transform

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from radar_3d_rolling_map_node import (  # noqa: E402
    filter_point_dicts, quaternion_rotate_translate, voxel_downsample)


def point_at_elevation(degrees, order=0):
    radians = math.radians(degrees)
    return {"x": math.cos(radians), "y": 0.0, "z": math.sin(radians),
            "snr": 20.0, "_order": (order, 0, 0)}


class RollingMapPureTests(unittest.TestCase):
    def test_elevation_boundaries_are_inclusive(self):
        inputs = [point_at_elevation(value, index)
                  for index, value in enumerate((-20, -10, 0, 30, 60, 70))]
        result = filter_point_dicts(inputs, 0.2, 3.0, -10.0, 60.0, 15.0)
        elevations = [round(math.degrees(math.atan2(p["z"], math.hypot(p["x"], p["y"]))))
                      for p in result]
        self.assertEqual(elevations, [-10, 0, 30, 60])

    def test_nan_inf_and_near_origin_are_removed(self):
        points = [
            {"x": float("nan"), "y": 1.0, "z": 0.0, "snr": 20.0},
            {"x": 1.0, "y": float("inf"), "z": 0.0, "snr": 20.0},
            {"x": 0.0, "y": 0.0, "z": 0.0, "snr": 20.0},
        ]
        self.assertEqual(filter_point_dicts(points, 0.0, 3.0, -10, 60, 15), [])

    def test_voxel_keeps_newest_and_max_points_can_keep_tail(self):
        old = {"x": 1.001, "y": 0.0, "z": 0.0, "_order": (1, 0, 0)}
        new = {"x": 1.002, "y": 0.0, "z": 0.0, "_order": (2, 0, 0)}
        other = {"x": 2.0, "y": 0.0, "z": 0.0, "_order": (3, 0, 0)}
        result = voxel_downsample([old, new, other], 0.05)
        self.assertEqual(result, [new, other])
        self.assertEqual(result[-1:], [other])

    def test_transform_rotation_and_translation(self):
        transform = Transform()
        transform.translation.x = 1.0
        transform.rotation.z = math.sin(math.pi / 4)
        transform.rotation.w = math.cos(math.pi / 4)
        result = quaternion_rotate_translate(
            {"x": 1.0, "y": 0.0, "z": 0.0}, transform)
        self.assertAlmostEqual(result["x"], 1.0, places=6)
        self.assertAlmostEqual(result["y"], 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
