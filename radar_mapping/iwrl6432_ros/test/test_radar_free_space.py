#!/usr/bin/env python3

import math
import unittest

from iwrl6432_ros.free_space import (
    bin_angles, contour_segments, corridor_candidates, free_space_boundary,
    interpolate_short_gaps, make_occupancy, nearest_ranges,
)


class FreeSpaceTest(unittest.TestCase):
    def setUp(self):
        self.angles = bin_angles(-60.0, 60.0, 3.0)

    @staticmethod
    def points_for(angles, distance):
        return [(distance * math.cos(math.radians(a)), distance * math.sin(math.radians(a)), 0.0, 20.0)
                for a in angles]

    def test_front_wall_contour_and_polygon(self):
        ranges = nearest_ranges(self.points_for(range(-30, 31, 3), 1.5),
                                0.2, 3.0, -60, 60, 3, 12, -0.3, 0.8)
        self.assertGreaterEqual(len(contour_segments(ranges, self.angles, 0.6)), 19)
        polygon = free_space_boundary(ranges, self.angles, 0.25, 0.5)
        self.assertEqual(len(polygon), 41)
        self.assertAlmostEqual(polygon[20][0], 1.25, places=5)

    def test_center_obstacle_leaves_two_corridors(self):
        points = self.points_for(range(-60, -8, 3), 2.2) + self.points_for(range(9, 61, 3), 2.2)
        points += self.points_for(range(-6, 7, 3), 0.7)
        ranges = nearest_ranges(points, 0.2, 3, -60, 60, 3, 12, -0.3, 0.8)
        candidates = corridor_candidates(ranges, self.angles, 3, 1.0, 0.35, 0.15, 15)
        self.assertEqual(len(candidates), 2)
        self.assertTrue(any(item["center_angle_deg"] < 0 for item in candidates))
        self.assertTrue(any(item["center_angle_deg"] > 0 for item in candidates))

    def test_left_wall_recommends_right(self):
        points = self.points_for(range(-60, -5, 3), 0.8) + self.points_for(range(0, 61, 3), 2.0)
        ranges = nearest_ranges(points, 0.2, 3, -60, 60, 3, 12, -0.3, 0.8)
        candidates = corridor_candidates(ranges, self.angles, 3, 1, 0.35, 0.15, 15)
        self.assertGreater(candidates[0]["center_angle_deg"], 0)
        self.assertTrue(-60 <= candidates[0]["center_angle_deg"] <= 60)

    def test_corridor_width_threshold(self):
        wide = [None] * len(self.angles)
        for index in range(17, 24):
            wide[index] = 2.0
        self.assertTrue(corridor_candidates(wide, self.angles, 3, 1, 0.35, 0.15, 15))
        narrow = [None] * len(self.angles)
        for index in range(18, 23):
            narrow[index] = 1.0
        self.assertFalse(corridor_candidates(narrow, self.angles, 3, 1, 0.35, 0.15, 15))

    def test_missing_bins_not_bridged(self):
        ranges = [None] * len(self.angles)
        ranges[5], ranges[10] = 1.0, 1.1
        self.assertEqual(interpolate_short_gaps(ranges, 2, 0.6)[7], None)
        self.assertEqual(contour_segments(ranges, self.angles, 0.6), [])

    def test_jump_breaks_contour(self):
        ranges = [None] * len(self.angles)
        ranges[10], ranges[11] = 0.8, 1.6
        self.assertEqual(contour_segments(ranges, self.angles, 0.6), [])

    def test_grid_dimensions_and_unknown(self):
        ranges = [None] * len(self.angles)
        ranges[20] = 1.5
        width, height, _ox, _oy, data = make_occupancy(
            ranges, self.angles, 0.05, 6.0, 6.0, 0, 0, 0.15, 0.25)
        self.assertEqual((width, height, len(data)), (120, 120, 14400))
        self.assertIn(-1, data)
        self.assertIn(0, data)
        self.assertIn(100, data)


if __name__ == "__main__":
    unittest.main()
