#!/usr/bin/env python3
import math
import unittest

from iwrl6432_ros.sector_occupancy import (
    build_background_profile, corridor_to_array, find_clear_runs,
    matches_background_voxel, persistence_statistics, recommended_sector,
    risk_score, sector_bounds,
    sector_index, select_low_occupancy_corridor, summarize_sector,
    valid_near_field_point, voxel_center, voxel_index, within_vertical_roi,
)


def point(x, y, z, snr=10.0, noise=80.0, doppler=0.0):
    return dict(x=x, y=y, z=z, snr=snr, noise=noise, doppler=doppler)


class BackgroundProfileTest(unittest.TestCase):
    def test_near_field_filter_preserves_negative_z(self):
        self.assertTrue(valid_near_field_point(point(.42, -.04, -.245), .1, 1., 8., 60.))

    def test_range_fov_snr_and_nan(self):
        self.assertFalse(valid_near_field_point(point(.09, 0, 0), .1, 1., 8., 60.))
        self.assertFalse(valid_near_field_point(point(.5, 0, 0, snr=7.9), .1, 1., 8., 60.))
        self.assertFalse(valid_near_field_point(point(.2, .5, 0), .1, 1., 8., 60.))
        self.assertFalse(valid_near_field_point(point(math.nan, 0, 0), .1, 1., 8., 60.))

    def test_vertical_roi_is_inclusive(self):
        self.assertFalse(within_vertical_roi(point(.2, 0, -.10), -.05, .30))
        self.assertTrue(within_vertical_roi(point(.2, 0, -.05), -.05, .30))
        self.assertTrue(within_vertical_roi(point(.2, 0, .00), -.05, .30))
        self.assertTrue(within_vertical_roi(point(.2, 0, .30), -.05, .30))
        self.assertFalse(within_vertical_roi(point(.2, 0, .31), -.05, .30))

    def test_vertical_roi_defaults_preserve_existing_behavior(self):
        self.assertTrue(within_vertical_roi(point(.2, 0, -123.0)))
        self.assertTrue(within_vertical_roi(point(.2, 0, 123.0)))

    def test_vertical_roi_rejects_reversed_range(self):
        with self.assertRaisesRegex(ValueError, "sector_min_z"):
            within_vertical_roi(point(.2, 0, 0), .30, -.05)

    def test_negative_voxel_floor_and_center(self):
        self.assertEqual(voxel_index(point(.42, -.04, -.245), .02), (21, -2, -13))
        self.assertEqual(voxel_center((21, -2, -13), .02), (.43, -.03, -.25))

    def test_profile_uses_distinct_frame_presence(self):
        stable = point(.42, -.04, -.245, snr=20)
        intermittent = point(.65, .30, 0, snr=18)
        frames = [[stable, stable, intermittent], [stable], [stable], [stable]]
        profile = build_background_profile(frames, .02, .90)
        self.assertEqual(len(profile), 1)
        self.assertEqual(profile[0]["index"], (21, -2, -13))
        self.assertEqual(profile[0]["frame_count"], 4)
        self.assertEqual(profile[0]["point_count"], 5)

    def test_background_neighbor_voxel_matching(self):
        profile = {(10, -3, 4)}
        self.assertTrue(matches_background_voxel(
            point(.21, -.05, .09), .02, profile, 0))
        self.assertFalse(matches_background_voxel(
            point(.23, -.05, .09), .02, profile, 0))
        self.assertTrue(matches_background_voxel(
            point(.23, -.05, .09), .02, profile, 1))
        self.assertTrue(matches_background_voxel(
            point(.23, -.07, .11), .02, profile, 1))
        self.assertFalse(matches_background_voxel(
            point(.25, -.05, .09), .02, profile, 1))

    def test_background_neighbor_radius_validation(self):
        with self.assertRaises(ValueError):
            matches_background_voxel(point(.2, 0, 0), .02, set(), -1)
        with self.assertRaises(ValueError):
            matches_background_voxel(point(.2, 0, 0), .02, set(), 1.5)

    def test_sector_order_is_left_to_right(self):
        half = math.radians(60)
        self.assertEqual(sector_index(math.radians(50), half, 5), 0)
        self.assertEqual(sector_index(0, half, 5), 2)
        self.assertEqual(sector_index(math.radians(-50), half, 5), 4)
        self.assertIsNone(sector_index(math.radians(61), half, 5))
        self.assertEqual([round(math.degrees((a+b)/2)) for a,b in sector_bounds(half,5)],
                         [48, 24, 0, -24, -48])

    def test_sector_summary_keeps_z(self):
        summary = summarize_sector([point(.4, 0, -.25), point(.5, 0, .15)], .02)
        self.assertEqual(summary["point_count"], 2)
        self.assertAlmostEqual(summary["average_z"], -.05)
        self.assertAlmostEqual(summary["min_z"], -.25)
        self.assertAlmostEqual(summary["max_z"], .15)

    def test_persistence_and_explainable_risk(self):
        history = [summarize_sector([point(.2, 0, 0)], .02),
                   summarize_sector([], .02),
                   summarize_sector([point(.4, 0, 0), point(.42, 0, 0)], .02)]
        presence, nearest, voxels = persistence_statistics(history)
        self.assertAlmostEqual(presence, 2/3)
        self.assertAlmostEqual(nearest, .3)
        self.assertEqual(voxels, 1.0)
        risk, distance, density, weights = risk_score(
            presence, nearest, voxels, .1, 1., 3., (.5, .35, .15))
        self.assertAlmostEqual(distance, 7/9)
        self.assertAlmostEqual(density, 1/3)
        self.assertAlmostEqual(risk, .5*(2/3)+.35*(7/9)+.15*(1/3))
        self.assertEqual(weights, (.5, .35, .15))

    def test_heading_policy_and_blocked_nan_condition(self):
        risks = [.2, .3, .1, .2, .4]
        nearest = [.8, .7, math.nan, .9, .8]
        self.assertEqual(recommended_sector(risks, nearest,
                                            [False, False, False, False, False]), 2)
        self.assertEqual(recommended_sector(risks, nearest,
                                            [False, False, True, False, False]), 3)
        self.assertIsNone(recommended_sector(risks, nearest,
                                             [True, True, True, True, True]))


class LowOccupancyCorridorTest(unittest.TestCase):
    def setUp(self):
        self.bounds = sector_bounds(math.radians(60), 5)
        self.nearest = [.8, .6, math.nan, .7, .9]

    def select(self, risks, occupied, heading=0.0):
        return select_low_occupancy_corridor(
            risks, self.nearest, occupied, self.bounds, heading)

    def test_three_clear_runs_select_center_s3(self):
        occupied = [False, True, False, True, False]
        runs = find_clear_runs([.1, .8, .2, .9, .3], self.nearest,
                               occupied, self.bounds)
        self.assertEqual(len(runs), 3)
        selected = self.select([.1, .8, .2, .9, .3], occupied)
        self.assertEqual((selected["start_index"], selected["end_index"]), (2, 2))

    def test_s2_through_s4_is_one_centered_run(self):
        occupied = [True, False, False, False, True]
        runs = find_clear_runs([.8, .2, .1, .3, .9], self.nearest,
                               occupied, self.bounds)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["start_index"], runs[0]["end_index"]), (1, 3))
        self.assertAlmostEqual(runs[0]["center_angle_rad"], 0.0)

    def test_symmetric_runs_choose_lower_mean_risk(self):
        occupied = [False, False, True, False, False]
        selected = self.select([.30, .20, .9, .10, .10], occupied,
                               heading=math.radians(-24))
        self.assertEqual((selected["start_index"], selected["end_index"]), (3, 4))

    def test_all_occupied_is_invalid_nan_and_zero_count(self):
        selected = self.select([.8] * 5, [True] * 5, heading=math.nan)
        data = corridor_to_array(selected)
        self.assertIsNone(selected)
        self.assertEqual(data[0], 0.0)
        self.assertTrue(math.isnan(data[3]))
        self.assertEqual(data[5], 0.0)

    def test_all_clear_is_full_centered_corridor(self):
        selected = self.select([.1] * 5, [False] * 5)
        self.assertEqual((selected["start_index"], selected["end_index"]), (0, 4))
        self.assertTrue(selected["contains_center_sector"])
        self.assertAlmostEqual(selected["center_heading_rad"], 0.0)

    def test_nan_nearest_is_not_zero_range(self):
        nearest = [math.nan] * 5
        selected = select_low_occupancy_corridor(
            [.1, .8, .2, .9, .3], nearest,
            [False, True, False, True, False], self.bounds, 0.0)
        self.assertTrue(math.isnan(selected["min_nearest_range_m"]))
        self.assertAlmostEqual(selected["center_heading_rad"], 0.0)

    def test_two_cans_select_s3_with_24_degree_width(self):
        selected = self.select([.1, .83, 0.0, .85, 0.0],
                               [False, True, False, True, False])
        self.assertEqual((selected["start_index"], selected["end_index"]), (2, 2))
        self.assertAlmostEqual(math.degrees(selected["center_heading_rad"]), 0.0)
        self.assertAlmostEqual(math.degrees(selected["angular_width_rad"]), 24.0)


if __name__ == "__main__":
    unittest.main()
