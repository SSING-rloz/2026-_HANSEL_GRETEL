#!/usr/bin/env python3

import math
import unittest

from iwrl6432_ros.manual_pose_mapping import (
    rotate_translate_3d, transform_xy, voxel_key,
)


class ManualPoseGeometryTest(unittest.TestCase):
    def test_translation(self):
        self.assertEqual(transform_xy(1.0, 2.0, 3.0, 4.0, 0.0), (4.0, 6.0))

    def test_quarter_turn(self):
        x_value, y_value = transform_xy(1.0, 0.0, 1.0, 2.0, math.pi/2.0)
        self.assertAlmostEqual(x_value, 1.0)
        self.assertAlmostEqual(y_value, 3.0)

    def test_sensor_to_base_rotation(self):
        half = math.sqrt(0.5)
        result = rotate_translate_3d(
            (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, -half, half))
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], -1.0)
        self.assertAlmostEqual(result[2], 0.0)

    def test_voxel_key(self):
        self.assertEqual(voxel_key((0.09, -0.01, 0.10), 0.05), (1, -1, 2))


if __name__ == "__main__":
    unittest.main()
