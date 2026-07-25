#!/usr/bin/env python3
import math
import os
import sys
import unittest
from unittest import mock

import rospy
import sensor_msgs.point_cloud2 as pc2
from sensor_msgs.msg import PointField
from std_msgs.msg import Header
from visualization_msgs.msg import Marker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from radar_dynamic_tracker_node import (  # noqa: E402
    POINT_FIELDS, RadarDynamicTracker, TrackManager, euclidean_clusters,
    filter_dynamic_points, marker_deletions)


def point(doppler=1.0, elevation=0.0, x_offset=0.0):
    angle = math.radians(elevation)
    return {"x": x_offset, "y": math.cos(angle), "z": math.sin(angle),
            "doppler": doppler, "snr": 20.0}


def fake_cloud(points, include_doppler=True):
    names = POINT_FIELDS if include_doppler else ("x", "y", "z", "snr")
    fields = [PointField(name=name, offset=index * 4,
                         datatype=PointField.FLOAT32, count=1)
              for index, name in enumerate(names)]
    rows = [[item[name] for name in names] for item in points]
    return pc2.create_cloud(Header(frame_id="radar_link", stamp=rospy.Time(10)), fields, rows)


class DynamicFilterTests(unittest.TestCase):
    def test_doppler_boundaries(self):
        values = [0.0, 0.14, 0.15, -0.15, 5.0, 5.1]
        decoded = RadarDynamicTracker.dictionaries_from_cloud(
            fake_cloud([point(value) for value in values]))
        result = filter_dynamic_points(decoded)
        self.assertEqual([round(item["doppler"], 2) for item in result],
                         [0.15, -0.15, 5.0])

    def test_elevation_boundaries_with_fake_pointcloud2(self):
        cloud = fake_cloud([point(1.0, angle) for angle in (-20, -10, 0, 60, 70)])
        decoded = RadarDynamicTracker.dictionaries_from_cloud(cloud)
        result = filter_dynamic_points(decoded)
        elevations = [round(math.degrees(math.atan2(
            item["z"], math.hypot(item["x"], item["y"])))) for item in result]
        self.assertEqual(elevations, [-10, 0, 60])

    def test_empty_and_missing_doppler_clouds(self):
        self.assertEqual(RadarDynamicTracker.dictionaries_from_cloud(fake_cloud([])), [])
        with mock.patch("rospy.logwarn_throttle") as warning:
            self.assertIsNone(RadarDynamicTracker.dictionaries_from_cloud(
                fake_cloud([point()], include_doppler=False)))
            warning.assert_called_once()


class ClusterTrackMarkerTests(unittest.TestCase):
    def test_connected_components(self):
        points = [point(x_offset=value) for value in (0.0, 0.10, 0.20, 1.3, 1.4)]
        clusters = euclidean_clusters(points, 0.45, 2)
        self.assertEqual(sorted(cluster["count"] for cluster in clusters), [2, 3])

    def test_track_id_timeout_and_delete_markers(self):
        manager = TrackManager(association_distance=0.7, timeout=1.0)
        first = euclidean_clusters([point(x_offset=0.0), point(x_offset=0.1)], 0.45, 2)
        visible, expired = manager.update(first, 10.0)
        self.assertEqual((visible[0][0], expired), (1, []))
        moved = euclidean_clusters([point(x_offset=0.2), point(x_offset=0.3)], 0.45, 2)
        visible, expired = manager.update(moved, 10.2)
        self.assertEqual((visible[0][0], expired), (1, []))
        visible, expired = manager.update([], 11.2)
        self.assertEqual(visible, [])
        self.assertEqual(expired, [1])
        deletes = marker_deletions(expired, "radar_link", rospy.Time(11, 200000000))
        self.assertEqual(len(deletes.markers), 4)
        self.assertTrue(all(marker.action == Marker.DELETE for marker in deletes.markers))
        self.assertNotIn(Marker.DELETEALL, [marker.action for marker in deletes.markers])


if __name__ == "__main__":
    unittest.main()
