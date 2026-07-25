"""Pure helpers for sparse-radar obstacle clustering, outlines, and gap scoring."""

import math


def valid_point(point, min_range, max_range, min_z, max_z, min_snr, half_fov):
    values = (point.get("x"), point.get("y"), point.get("z"))
    if any(value is None or not math.isfinite(value) for value in values):
        return False
    snr = point.get("snr")
    if snr is not None and (not math.isfinite(snr) or snr < min_snr):
        return False
    radius = math.hypot(point["x"], point["y"])
    angle = math.degrees(math.atan2(point["y"], point["x"]))
    return (min_range <= radius <= max_range and min_z <= point["z"] <= max_z and
            -half_fov <= angle <= half_fov)


def voxel_downsample(points, size):
    if size <= 0:
        return list(points)
    voxels = {}
    for point in points:
        key = tuple(int(math.floor(point[name] / size)) for name in ("x", "y", "z"))
        previous = voxels.get(key)
        if previous is None or point.get("stamp", 0.0) >= previous.get("stamp", 0.0):
            voxels[key] = point
    return list(voxels.values())


def euclidean_clusters(points, eps, min_points, max_clusters):
    """DBSCAN-equivalent connected components with no dependency or noise merging."""
    if eps <= 0 or min_points <= 0 or max_clusters <= 0:
        raise ValueError("invalid clustering parameters")
    squared = eps * eps
    unseen = set(range(len(points)))
    clusters = []
    while unseen:
        seed = unseen.pop()
        component = [seed]
        queue = [seed]
        while queue:
            current = queue.pop()
            nearby = []
            a = points[current]
            for candidate in unseen:
                b = points[candidate]
                distance = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 +
                            (a["z"] - b["z"]) ** 2)
                if distance <= squared:
                    nearby.append(candidate)
            for candidate in nearby:
                unseen.remove(candidate)
                component.append(candidate)
                queue.append(candidate)
        if len(component) >= min_points:
            clusters.append([points[index] for index in component])
    clusters.sort(key=lambda group: (-len(group), min(math.hypot(p["x"], p["y"]) for p in group)))
    return clusters[:max_clusters]


def convex_hull_xy(points):
    """Monotonic-chain hull; returns unique XY vertices without repeating the first."""
    unique = sorted(set((float(p["x"]), float(p["y"])) for p in points))
    if len(unique) <= 1:
        return unique

    def cross(origin, first, second):
        return ((first[0] - origin[0]) * (second[1] - origin[1]) -
                (first[1] - origin[1]) * (second[0] - origin[0]))

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def outline_xy(points, minimum_thickness=0.06):
    hull = convex_hull_xy(points)
    if len(hull) != 2:
        return hull
    (x0, y0), (x1, y1) = hull
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return [hull[0]]
    offset_x = -dy / length * minimum_thickness * 0.5
    offset_y = dx / length * minimum_thickness * 0.5
    return [(x0 + offset_x, y0 + offset_y), (x1 + offset_x, y1 + offset_y),
            (x1 - offset_x, y1 - offset_y), (x0 - offset_x, y0 - offset_y)]


def describe_cluster(points):
    count = len(points)
    centroid = tuple(sum(p[name] for p in points) / count for name in ("x", "y", "z"))
    ranges = [math.hypot(p["x"], p["y"]) for p in points]
    angles = [math.degrees(math.atan2(p["y"], p["x"])) for p in points]
    snrs = [p["snr"] for p in points if p.get("snr") is not None and math.isfinite(p["snr"])]
    minimum = tuple(min(p[name] for p in points) for name in ("x", "y", "z"))
    maximum = tuple(max(p[name] for p in points) for name in ("x", "y", "z"))
    return {
        "points": points, "centroid": centroid, "minimum": minimum, "maximum": maximum,
        "count": count, "average_range_m": sum(ranges) / count,
        "average_angle_deg": sum(angles) / count, "min_range_m": min(ranges),
        "max_range_m": max(ranges), "min_angle_deg": min(angles),
        "max_angle_deg": max(angles), "average_snr": sum(snrs) / len(snrs) if snrs else None,
        "width_m": maximum[1] - minimum[1], "depth_m": maximum[0] - minimum[0],
        "outline": outline_xy(points),
    }


class StableClusterIds:
    def __init__(self, association_distance=0.55, timeout_sec=1.2):
        self.association_distance = association_distance
        self.timeout = timeout_sec
        self.next_id = 1
        self.tracks = {}

    def update(self, clusters, now):
        candidates = []
        for track_id, previous in self.tracks.items():
            for index, cluster in enumerate(clusters):
                distance = math.sqrt(sum((previous[axis] - cluster["centroid"][axis]) ** 2
                                         for axis in range(3)))
                if distance <= self.association_distance:
                    candidates.append((distance, track_id, index))
        used_tracks, used_clusters, assignments = set(), set(), {}
        for _distance, track_id, index in sorted(candidates):
            if track_id not in used_tracks and index not in used_clusters:
                assignments[index] = track_id
                used_tracks.add(track_id)
                used_clusters.add(index)
        for index, cluster in enumerate(clusters):
            track_id = assignments.get(index)
            if track_id is None:
                track_id = self.next_id
                self.next_id += 1
            cluster["id"] = track_id
            self.tracks[track_id] = tuple(cluster["centroid"]) + (now,)
        expired = [track_id for track_id, value in self.tracks.items()
                   if now - value[3] >= self.timeout]
        for track_id in expired:
            del self.tracks[track_id]
        return clusters, expired


def angular_gaps(clusters, half_fov, min_clearance):
    """Build internal and low-confidence edge gaps; no obstacles means no known gap."""
    if not clusters:
        return []
    ordered = sorted(clusters, key=lambda item: item["min_angle_deg"])
    gaps = []

    def add_gap(start, end, left, right, confidence):
        if end <= start:
            return
        boundaries = [item for item in (left, right) if item is not None]
        nearest = min(item["min_range_m"] for item in boundaries)
        angle_width = end - start
        estimated = 2.0 * nearest * math.tan(math.radians(angle_width) * 0.5)
        gaps.append({"start_angle_deg": start, "end_angle_deg": end,
                     "center_angle_deg": 0.5 * (start + end),
                     "angular_width_deg": angle_width, "estimated_width_m": estimated,
                     "nearest_obstacle_range_m": nearest,
                     "confidence": confidence,
                     "bounded_both_sides": left is not None and right is not None,
                     "clearance_ok": nearest >= min_clearance})

    add_gap(-half_fov, ordered[0]["min_angle_deg"], None, ordered[0], 0.35)
    for left, right in zip(ordered, ordered[1:]):
        support = min(1.0, min(left["count"], right["count"]) / 3.0)
        add_gap(left["max_angle_deg"], right["min_angle_deg"], left, right,
                0.65 + 0.35 * support)
    add_gap(ordered[-1]["max_angle_deg"], half_fov, ordered[-1], None, 0.35)
    return gaps


def traversable_gaps(gaps, robot_width, safety_margin, min_gap_width,
                     min_gap_angle, min_confidence=0.3):
    required = max(min_gap_width, robot_width + 2.0 * safety_margin)
    output = []
    for gap in gaps:
        if (gap["estimated_width_m"] < required or
                gap["angular_width_deg"] < min_gap_angle or
                not gap["clearance_ok"] or gap["confidence"] < min_confidence):
            continue
        width_norm = min(1.0, gap["estimated_width_m"] / 2.0)
        clearance_norm = min(1.0, gap["nearest_obstacle_range_m"] / 3.0)
        forward = max(0.0, 1.0 - abs(gap["center_angle_deg"]) / 60.0)
        # Explicit requested weighting: width, clearance, forward preference, confidence.
        gap = dict(gap)
        gap["score"] = (1.0 * width_norm + 0.7 * clearance_norm +
                        0.4 * forward + 0.5 * gap["confidence"])
        output.append(gap)
    return sorted(output, key=lambda item: item["score"], reverse=True)


def xy_gaps(clusters, half_fov, max_depth_offset=0.25):
    """Measure internal gaps from real XY boundary pairs.

    Clusters are ordered from negative to positive base_link Y. Only point pairs
    with similar forward X are eligible; this avoids calling staggered obstacles
    a door-like passage. FOV edge regions are reported as open/unknown with no
    fabricated metric width.
    """
    if not clusters:
        return []
    ordered = sorted(clusters, key=lambda item: item["centroid"][1])
    gaps = [{"kind": "open_edge", "side": "right", "bounded_both_sides": False,
             "confidence": 0.2, "estimated_width_m": None,
             "start_angle_deg": -half_fov,
             "end_angle_deg": ordered[0]["min_angle_deg"]}]
    for lower, upper in zip(ordered, ordered[1:]):
        pairs = []
        for lower_point in lower["points"]:
            for upper_point in upper["points"]:
                depth_delta = abs(lower_point["x"] - upper_point["x"])
                if depth_delta <= max_depth_offset:
                    distance = math.hypot(lower_point["x"] - upper_point["x"],
                                          lower_point["y"] - upper_point["y"])
                    pairs.append((distance, depth_delta, lower_point, upper_point))
        if not pairs:
            gaps.append({"kind": "depth_mismatch", "bounded_both_sides": True,
                         "confidence": 0.0, "estimated_width_m": None,
                         "left_cluster_id": upper.get("id"),
                         "right_cluster_id": lower.get("id")})
            continue
        width, depth_delta, right_point, left_point = min(pairs, key=lambda item: item[0])
        center_x = 0.5 * (right_point["x"] + left_point["x"])
        center_y = 0.5 * (right_point["y"] + left_point["y"])
        start_angle = math.degrees(math.atan2(right_point["y"], right_point["x"]))
        end_angle = math.degrees(math.atan2(left_point["y"], left_point["x"]))
        support = min(1.0, min(lower["count"], upper["count"]) / 3.0)
        alignment = max(0.0, 1.0 - depth_delta / max_depth_offset)
        confidence = 0.55 + 0.25 * support + 0.20 * alignment
        gaps.append({
            "kind": "internal", "bounded_both_sides": True,
            "left_cluster_id": upper.get("id"), "right_cluster_id": lower.get("id"),
            "right_boundary": (right_point["x"], right_point["y"]),
            "left_boundary": (left_point["x"], left_point["y"]),
            "center": (center_x, center_y),
            "center_angle_deg": math.degrees(math.atan2(center_y, center_x)),
            "start_angle_deg": start_angle, "end_angle_deg": end_angle,
            "angular_width_deg": max(0.0, end_angle - start_angle),
            "estimated_width_m": width,
            "nearest_obstacle_range_m": min(
                math.hypot(right_point["x"], right_point["y"]),
                math.hypot(left_point["x"], left_point["y"])),
            "depth_delta_m": depth_delta, "confidence": confidence,
        })
    gaps.append({"kind": "open_edge", "side": "left", "bounded_both_sides": False,
                 "confidence": 0.2, "estimated_width_m": None,
                 "start_angle_deg": ordered[-1]["max_angle_deg"],
                 "end_angle_deg": half_fov})
    return gaps


def traversable_xy_gaps(gaps, robot_width, safety_margin, min_gap_width):
    """Score only two-sided, depth-aligned gaps with measured XY width."""
    required = max(min_gap_width, robot_width + 2.0 * safety_margin)
    output = []
    for original in gaps:
        width = original.get("estimated_width_m")
        if (original.get("kind") != "internal" or width is None or width < required):
            continue
        gap = dict(original)
        width_norm = min(1.0, width / 1.0)
        clearance_norm = min(1.0, gap["nearest_obstacle_range_m"] / 1.0)
        forward = max(0.0, 1.0 - abs(gap["center_angle_deg"]) / 60.0)
        gap["required_width_m"] = required
        gap["score"] = (1.0 * width_norm + 0.7 * clearance_norm +
                        0.4 * forward + 0.5 * gap["confidence"])
        output.append(gap)
    return sorted(output, key=lambda item: item["score"], reverse=True)
