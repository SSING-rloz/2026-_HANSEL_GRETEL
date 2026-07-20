#!/usr/bin/env python3
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from radar_3d_fov_guides_node import spherical_point  # noqa: E402


class Radar3DFovAxesTests(unittest.TestCase):
    def test_front_is_positive_y(self):
        point = spherical_point(1.0, 0.0, 0.0)
        self.assertAlmostEqual(point.x, 0.0)
        self.assertAlmostEqual(point.y, 1.0)
        self.assertAlmostEqual(point.z, 0.0)

    def test_positive_azimuth_is_physical_left_negative_x(self):
        point = spherical_point(1.0, 60.0, 0.0)
        self.assertLess(point.x, 0.0)
        self.assertAlmostEqual(point.y, 0.5)

    def test_negative_azimuth_is_physical_right_positive_x(self):
        point = spherical_point(1.0, -60.0, 0.0)
        self.assertGreater(point.x, 0.0)
        self.assertAlmostEqual(point.y, 0.5)

    def test_up_is_positive_z(self):
        point = spherical_point(1.0, 0.0, 60.0)
        self.assertAlmostEqual(point.y, 0.5)
        self.assertAlmostEqual(point.z, math.sin(math.radians(60.0)))


if __name__ == "__main__":
    unittest.main()
