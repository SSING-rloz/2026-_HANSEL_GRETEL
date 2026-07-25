#!/usr/bin/env python3

import math
import os
import sys
import unittest
from collections import deque
from unittest import mock

import rospy
import sensor_msgs.point_cloud2 as pc2
import tf2_ros
from sensor_msgs.msg import PointField
from std_msgs.msg import Header
from visualization_msgs.msg import Marker, MarkerArray

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from radar_obstacle_contour_node import RadarObstacleContour  # noqa: E402
from radar_rviz_guides_node import RadarRvizGuides  # noqa: E402
from iwrl6432_ros.obstacle_contour import (  # noqa: E402
    StableClusterIds, angular_gaps, convex_hull_xy, describe_cluster,
    euclidean_clusters, outline_xy, traversable_gaps,
    traversable_xy_gaps, valid_point, voxel_downsample, xy_gaps,
)


def point(x, y, z=0.0, snr=20.0):
    return {"x": x, "y": y, "z": z, "snr": snr, "stamp": 1.0}


def polar(angle, radius=2.0):
    value = math.radians(angle)
    return point(radius * math.cos(value), radius * math.sin(value))


def cluster(angles, radius=2.0):
    return describe_cluster([polar(value, radius) for value in angles])


def fake_cloud(points, frame="base_link", snr=True):
    names = ("x", "y", "z", "snr") if snr else ("x", "y", "z")
    fields = [PointField(name=name, offset=index * 4,
                         datatype=PointField.FLOAT32, count=1)
              for index, name in enumerate(names)]
    return pc2.create_cloud(Header(frame_id=frame, stamp=rospy.Time(10)), fields,
                            [[item[name] for name in names] for item in points])


class ClusteringOutlineTests(unittest.TestCase):
    def test_two_boxes_remain_two_clusters(self):
        points = [point(1.4, y) for y in (-0.65, -0.55, -0.45)]
        points += [point(1.4, y) for y in (0.45, 0.55, 0.65)]
        groups = euclidean_clusters(points, 0.35, 2, 12)
        self.assertEqual([len(group) for group in groups], [3, 3])

    def test_single_point_is_noise(self):
        self.assertEqual(euclidean_clusters([point(1, 0)], 0.35, 2, 12), [])

    def test_two_point_outline_has_minimum_thickness(self):
        outline = outline_xy([point(1, 0), point(1, 0.2)])
        self.assertEqual(len(outline), 4)
        self.assertGreater(max(x for x, _y in outline) - min(x for x, _y in outline), 0.05)

    def test_convex_hull_uses_actual_points(self):
        points = [point(1, 0), point(2, 0), point(2, 1), point(1, 1), point(1.5, 0.5)]
        self.assertEqual(set(convex_hull_xy(points)), {(1, 0), (2, 0), (2, 1), (1, 1)})

    def test_stable_cluster_id(self):
        tracker = StableClusterIds(0.55, 1.2)
        first, _ = tracker.update([cluster((-22, -20, -18))], 1.0)
        second, _ = tracker.update([cluster((-20, -18, -16))], 1.2)
        self.assertEqual(first[0]["id"], second[0]["id"])


class GapTests(unittest.TestCase):
    def candidates(self, clusters):
        return traversable_gaps(angular_gaps(clusters, 60, 0.8), 0.35, 0.15, 0.65, 12)

    def test_two_boxes_central_gap_and_heading(self):
        values = self.candidates([cluster((-25, -22, -18)), cluster((18, 22, 25))])
        self.assertTrue(values)
        self.assertTrue(values[0]["bounded_both_sides"])
        self.assertAlmostEqual(values[0]["center_angle_deg"], 0.0)

    def test_central_obstacle_prefers_wider_left_gap(self):
        values = self.candidates([cluster((-5, 5, 15))])
        self.assertLess(values[0]["center_angle_deg"], 0.0)
        self.assertFalse(values[0]["bounded_both_sides"])
        self.assertEqual(values[0]["confidence"], 0.35)

    def test_left_obstacle_recommends_right(self):
        values = self.candidates([cluster((-42, -32, -22))])
        self.assertGreater(values[0]["center_angle_deg"], 0.0)

    def test_narrow_gap_is_not_traversable(self):
        gaps = angular_gaps([cluster((-20, -10, -2)), cluster((2, 10, 20))], 60, 0.8)
        internal = [gap for gap in gaps if gap["bounded_both_sides"]]
        self.assertLess(internal[0]["estimated_width_m"], 0.65)
        self.assertFalse(any(item["bounded_both_sides"] for item in
                             traversable_gaps(gaps, 0.35, 0.15, 0.65, 12)))

    def test_wide_gap_is_traversable(self):
        values = self.candidates([cluster((-25, -20, -15)), cluster((15, 20, 25))])
        self.assertTrue(any(item["bounded_both_sides"] and item["estimated_width_m"] >= 0.65
                            for item in values))

    def test_no_obstacles_is_unknown_not_free(self):
        self.assertEqual(angular_gaps([], 60, 0.8), [])
        self.assertEqual(self.candidates([]), [])

    def test_no_candidate_heading_is_nan(self):
        candidates = self.candidates([])
        heading = candidates[0]["center_angle_deg"] if candidates else float("nan")
        self.assertTrue(math.isnan(heading))

    @staticmethod
    def xy_cluster(x_value, inner_y, outer_y):
        return describe_cluster([point(x_value, inner_y), point(x_value + 0.02, outer_y)])

    def test_xy_gap_width_below_040_is_blocked(self):
        right = self.xy_cluster(0.6, -0.195, -0.30)
        left = self.xy_cluster(0.6, 0.195, 0.30)
        gaps = xy_gaps([right, left], 60, 0.25)
        internal = [item for item in gaps if item["kind"] == "internal"]
        self.assertAlmostEqual(internal[0]["estimated_width_m"], 0.39, places=6)
        self.assertEqual(traversable_xy_gaps(gaps, 0.35, 0.025, 0.40), [])

    def test_xy_gap_width_at_040_is_traversable_and_centered(self):
        right = describe_cluster([point(0.6, -0.20), point(0.62, -0.30)])
        left = describe_cluster([point(0.6, 0.20), point(0.62, 0.30)])
        values = traversable_xy_gaps(xy_gaps([right, left], 60, 0.25),
                                     0.35, 0.025, 0.40)
        self.assertEqual(len(values), 1)
        self.assertAlmostEqual(values[0]["estimated_width_m"], 0.40, places=6)
        self.assertAlmostEqual(values[0]["center_angle_deg"], 0.0, places=6)

    def test_depth_staggered_obstacles_are_not_a_door(self):
        right = self.xy_cluster(0.3, -0.20, -0.30)
        left = self.xy_cluster(0.8, 0.20, 0.30)
        gaps = xy_gaps([right, left], 60, 0.25)
        self.assertTrue(any(item["kind"] == "depth_mismatch" for item in gaps))
        self.assertEqual(traversable_xy_gaps(gaps, 0.35, 0.025, 0.40), [])

    def test_open_edges_are_unknown_not_traversable(self):
        gaps = xy_gaps([self.xy_cluster(0.6, -0.1, 0.1)], 60, 0.25)
        self.assertEqual([item["kind"] for item in gaps], ["open_edge", "open_edge"])
        self.assertEqual(traversable_xy_gaps(gaps, 0.35, 0.025, 0.40), [])


class NodeEdgeTests(unittest.TestCase):
    def bare_node(self):
        node = RadarObstacleContour.__new__(RadarObstacleContour)
        node.frame_id = "base_link"
        node.valid_min_range, node.max_range = 0.10, 1.0
        node.min_z, node.max_z, node.min_snr, node.half_fov = -0.25, 0.6, 8.0, 60.0
        return node

    def test_empty_cloud_and_missing_snr(self):
        node = self.bare_node()
        points, names = node.read_transformed(fake_cloud([], snr=False))
        self.assertEqual((points, names), ([], ("x", "y", "z")))
        points, _ = node.read_transformed(fake_cloud([point(1, 0)], snr=False))
        self.assertEqual(len(points), 1)

    def test_tf_unavailable_returns_none(self):
        node = self.bare_node()
        node.tf_buffer = mock.Mock()
        node.tf_buffer.lookup_transform.side_effect = tf2_ros.LookupException("missing")
        with mock.patch("rospy.logwarn_throttle"):
            points, _ = node.read_transformed(fake_cloud([point(1, 0)], frame="radar_link"))
        self.assertIsNone(points)

    def test_marker_deletion_has_no_deleteall(self):
        array = MarkerArray()
        RadarObstacleContour.delete_missing(
            array, ("a", "b"), {1, 2}, {2}, rospy.Time(10), "base_link")
        self.assertEqual(len(array.markers), 2)
        self.assertTrue(all(item.action == Marker.DELETE for item in array.markers))
        self.assertNotIn(Marker.DELETEALL, [item.action for item in array.markers])

    def test_cluster_cloud_and_marker_publications(self):
        node = self.bare_node()
        node.cluster_pub = mock.Mock()
        node.filtered_pub = mock.Mock()
        node.outline_pub = mock.Mock()
        node.gap_pub = mock.Mock()
        node.debug_pub = mock.Mock()
        node.previous_outline_ids = set()
        node.previous_gap_ids = set()
        node.previous_debug_ids = set()
        item = cluster((-22, -20, -18))
        item["id"] = 7
        right = describe_cluster([point(0.6, -0.20), point(0.62, -0.30)])
        left = describe_cluster([point(0.6, 0.20), point(0.62, 0.30)])
        gap = traversable_xy_gaps(xy_gaps([right, left], 60, 0.25),
                                  0.35, 0.025, 0.40)[0]
        stamp = rospy.Time(10)
        node.publish_cloud([item], ("x", "y", "z", "snr"), stamp)
        node.publish_filtered(item["points"][:1], ("x", "y", "z", "snr"), stamp)
        node.publish_outlines([item], stamp)
        node.publish_gaps([gap], stamp)
        node.publish_debug(item["points"], [item], [gap], stamp)
        cloud = node.cluster_pub.publish.call_args[0][0]
        self.assertEqual(cloud.width, 3)
        self.assertIn("cluster_id", [field.name for field in cloud.fields])
        filtered = node.filtered_pub.publish.call_args[0][0]
        self.assertEqual(filtered.width, 1)
        self.assertNotIn("cluster_id", [field.name for field in filtered.fields])
        outlines = node.outline_pub.publish.call_args[0][0].markers
        self.assertEqual(len(outlines), 2)
        debug = node.debug_pub.publish.call_args[0][0].markers
        self.assertTrue(any(marker.ns == "debug_cluster_label" for marker in debug))
        gaps = node.gap_pub.publish.call_args[0][0].markers
        self.assertTrue(any(marker.type == Marker.ARROW for marker in gaps))

    def test_nan_and_low_snr_filter(self):
        self.assertFalse(valid_point(point(float("nan"), 0), .2, 3, -.3, .8, 10, 60))
        self.assertFalse(valid_point(point(1, 0, snr=9), .2, 3, -.3, .8, 10, 60))

    def test_near_field_010_boundary_is_inclusive(self):
        args = (0.10, 1.0, -0.25, 0.6, 8.0, 60.0)
        self.assertFalse(valid_point(point(0.099, 0), *args))
        self.assertTrue(valid_point(point(0.100, 0), *args))
        self.assertTrue(valid_point(point(0.101, 0), *args))

    def test_main_z_minus_010_boundary_is_inclusive(self):
        args = (0.10, 1.0, -0.10, 0.6, 8.0, 60.0)
        self.assertFalse(valid_point(point(0.5, 0, z=-0.101), *args))
        self.assertTrue(valid_point(point(0.5, 0, z=-0.100), *args))
        self.assertTrue(valid_point(point(0.5, 0, z=-0.099), *args))

    def test_current_filter_history_and_clustering_exclude_sub_010(self):
        node = self.bare_node()
        node.frames = deque(maxlen=8)
        node.history_duration = 1.5
        node.voxel_size = 0.02
        node.max_accumulated_points = 3000
        node.cluster_eps, node.cluster_min_points, node.max_clusters = 0.15, 2, 12
        node.half_fov, node.max_gap_depth_offset = 60.0, 0.25
        node.robot_width, node.safety_margin, node.min_gap_width = 0.35, 0.025, 0.40
        node.tracker = mock.Mock()
        node.tracker.update.return_value = ([], [])
        node.heading_pub = mock.Mock()
        node.publish_filtered = mock.Mock()
        node.publish_cloud = mock.Mock()
        node.publish_outlines = mock.Mock()
        node.publish_gaps = mock.Mock()
        node.publish_debug = mock.Mock()
        cloud = fake_cloud([point(0.099, 0), point(0.100, 0), point(0.101, 0)])
        with mock.patch("radar_obstacle_contour_node.euclidean_clusters", return_value=[]) as clustering:
            node.callback(cloud)
        current = node.publish_filtered.call_args[0][0]
        history = [item for _stamp, frame in node.frames for item in frame]
        clustered_input = clustering.call_args[0][0]
        self.assertEqual(len(current), 2)
        self.assertTrue(all(math.hypot(item["x"], item["y"]) >= 0.10 for item in current))
        self.assertTrue(all(math.hypot(item["x"], item["y"]) >= 0.10 for item in history))
        self.assertTrue(all(math.hypot(item["x"], item["y"]) >= 0.10
                            for item in clustered_input))

    def test_near_field_voxel_is_002(self):
        old = point(0.501, 0.0)
        old["stamp"] = 1.0
        new = point(0.519, 0.0)
        new["stamp"] = 2.0
        separate = point(0.521, 0.0)
        separate["stamp"] = 3.0
        result = voxel_downsample([old, new, separate], 0.02)
        self.assertEqual(result, [new, separate])

    def test_cluster_eps_015_does_not_merge_nearby_obstacles(self):
        first = [point(0.5, -0.20), point(0.5, -0.16)]
        second = [point(0.5, 0.04), point(0.5, 0.08)]
        self.assertEqual(len(euclidean_clusters(first + second, 0.15, 2, 12)), 2)

    def test_presentation_guides_are_minimal_and_spaced_020(self):
        guides = RadarRvizGuides.__new__(RadarRvizGuides)
        guides.frame_id = "base_link"
        guides.max_range = 1.0
        guides.ring_interval = 0.2
        guides.fov_deg = 60.0
        guides.show_labels = True
        with mock.patch("rospy.Time.now", return_value=rospy.Time(10)):
            markers = guides.build().markers
        texts = [marker.text for marker in markers if marker.type == Marker.TEXT_VIEW_FACING]
        rings = [marker for marker in markers if marker.ns == "range_rings"]
        self.assertEqual(texts, ["FRONT", "0.2 m", "0.4 m", "0.6 m", "0.8 m", "1.0 m"])
        self.assertEqual(len(rings), 5)
        self.assertFalse(any(marker.ns in ("risk_zones", "risk_labels", "origin_label")
                             for marker in markers))

if __name__ == "__main__":
    unittest.main()
