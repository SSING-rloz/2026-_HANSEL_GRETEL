"""Pure helpers for 3D background voxels and angular sector occupancy."""

from collections import defaultdict
import math
import statistics

import yaml


POINT_FIELDS = ("x", "y", "z", "doppler", "snr", "noise")


def valid_near_field_point(point, min_range, max_range, min_snr, half_fov_deg):
    """Validate XY range/FOV/SNR without applying a global Z-height filter."""
    xyz = tuple(point.get(name) for name in ("x", "y", "z"))
    if any(value is None or not math.isfinite(value) for value in xyz):
        return False
    snr = point.get("snr")
    if snr is not None and (not math.isfinite(snr) or snr < min_snr):
        return False
    range_xy = math.hypot(point["x"], point["y"])
    azimuth_deg = math.degrees(math.atan2(point["y"], point["x"]))
    return (min_range <= range_xy <= max_range and
            -half_fov_deg <= azimuth_deg <= half_fov_deg)


def within_vertical_roi(point, min_z=float("-inf"), max_z=float("inf")):
    """Return whether a point is inside the inclusive sector-risk Z ROI."""
    if math.isnan(min_z) or math.isnan(max_z) or min_z > max_z:
        raise ValueError("sector_min_z must not exceed sector_max_z")
    z_value = point.get("z")
    return (z_value is not None and math.isfinite(z_value) and
            min_z <= z_value <= max_z)


def voxel_index(point, voxel_size):
    if voxel_size <= 0:
        raise ValueError("voxel_size must be positive")
    return tuple(int(math.floor(float(point[name]) / voxel_size))
                 for name in ("x", "y", "z"))


def voxel_center(index, voxel_size):
    return tuple((value + 0.5) * voxel_size for value in index)


def matches_background_voxel(point, voxel_size, background_voxels,
                             neighbor_radius=0):
    """Match a point against the profile voxel or its neighboring voxels.

    ``neighbor_radius`` uses Chebyshev voxel distance: radius 1 searches the
    complete 3x3x3 neighborhood.  Keeping radius 0 preserves exact matching.
    """
    if isinstance(neighbor_radius, bool) or not isinstance(neighbor_radius, int):
        raise ValueError("neighbor_radius must be a nonnegative integer")
    if neighbor_radius < 0:
        raise ValueError("neighbor_radius must be a nonnegative integer")
    point_index = voxel_index(point, voxel_size)
    if point_index in background_voxels:
        return True
    if neighbor_radius == 0:
        return False
    px, py, pz = point_index
    for dx in range(-neighbor_radius, neighbor_radius + 1):
        for dy in range(-neighbor_radius, neighbor_radius + 1):
            for dz in range(-neighbor_radius, neighbor_radius + 1):
                if (px + dx, py + dy, pz + dz) in background_voxels:
                    return True
    return False


def build_background_profile(frames, voxel_size, minimum_presence_ratio):
    """Return voxels seen in the requested fraction of distinct input frames."""
    if not frames:
        raise ValueError("background calibration requires at least one frame")
    if not 0.0 < minimum_presence_ratio <= 1.0:
        raise ValueError("minimum_presence_ratio must be in (0, 1]")
    samples = defaultdict(list)
    presence = defaultdict(int)
    for frame in frames:
        frame_voxels = defaultdict(list)
        for point in frame:
            frame_voxels[voxel_index(point, voxel_size)].append(point)
        for index, points in frame_voxels.items():
            presence[index] += 1
            samples[index].extend(points)
    total_frames = len(frames)
    profile = []
    for index, frame_count in presence.items():
        ratio = frame_count / float(total_frames)
        if ratio < minimum_presence_ratio:
            continue
        points = samples[index]
        entry = {
            "index": index,
            "center": voxel_center(index, voxel_size),
            "frame_count": frame_count,
            "total_frames": total_frames,
            "presence_ratio": ratio,
            "point_count": len(points),
        }
        for name in ("snr", "noise", "doppler"):
            values = [float(point[name]) for point in points
                      if point.get(name) is not None and math.isfinite(point[name])]
            entry["average_" + name] = sum(values) / len(values) if values else None
        profile.append(entry)
    profile.sort(key=lambda item: (-item["presence_ratio"], -item["frame_count"],
                                   item["index"]))
    return profile


def profile_document(profile, voxel_size, minimum_presence_ratio, total_frames,
                     source_frame="base_link"):
    return {
        "format_version": 1,
        "frame_id": source_frame,
        "voxel_size_m": float(voxel_size),
        "minimum_presence_ratio": float(minimum_presence_ratio),
        "total_frames": int(total_frames),
        "voxels": [{
            "index": list(item["index"]),
            "center": list(item["center"]),
            "frame_count": int(item["frame_count"]),
            "total_frames": int(item["total_frames"]),
            "presence_ratio": float(item["presence_ratio"]),
            "point_count": int(item["point_count"]),
            "average_snr": item["average_snr"],
            "average_noise": item["average_noise"],
            "average_doppler": item["average_doppler"],
        } for item in profile],
    }


def load_background_profile(path, expected_frame="base_link"):
    with open(path, "r", encoding="utf-8") as stream:
        document = yaml.safe_load(stream)
    if not isinstance(document, dict) or document.get("format_version") != 1:
        raise ValueError("unsupported background profile format")
    if document.get("frame_id") != expected_frame:
        raise ValueError("background profile frame does not match output frame")
    voxel_size = float(document["voxel_size_m"])
    if voxel_size <= 0:
        raise ValueError("background profile voxel size must be positive")
    voxels = set()
    for item in document.get("voxels", []):
        index = item.get("index")
        if not isinstance(index, list) or len(index) != 3:
            raise ValueError("invalid background voxel index")
        voxels.add(tuple(int(value) for value in index))
    return voxel_size, voxels, document


def sector_index(azimuth_rad, half_fov_rad, sector_count):
    """Return a left-to-right sector index, or None outside the FOV."""
    if sector_count <= 0 or not 0 < half_fov_rad <= math.pi:
        raise ValueError("invalid sector geometry")
    if azimuth_rad < -half_fov_rad or azimuth_rad > half_fov_rad:
        return None
    width = 2.0 * half_fov_rad / sector_count
    index = int((half_fov_rad - azimuth_rad) / width)
    return min(sector_count - 1, max(0, index))


def sector_bounds(half_fov_rad, sector_count):
    width = 2.0 * half_fov_rad / sector_count
    return [(half_fov_rad - index * width,
             half_fov_rad - (index + 1) * width)
            for index in range(sector_count)]


def summarize_sector(points, voxel_size):
    if not points:
        return {
            "point_count": 0, "voxel_count": 0, "nearest_range": float("nan"),
            "average_range": float("nan"), "average_z": float("nan"),
            "min_z": float("nan"), "max_z": float("nan"),
            "average_snr": float("nan"), "average_noise": float("nan"),
            "average_doppler": float("nan"),
        }
    ranges = [math.hypot(point["x"], point["y"]) for point in points]
    def average(name):
        values = [float(point[name]) for point in points
                  if point.get(name) is not None and math.isfinite(point[name])]
        return sum(values) / len(values) if values else float("nan")
    return {
        "point_count": len(points),
        "voxel_count": len({voxel_index(point, voxel_size) for point in points}),
        "nearest_range": min(ranges), "average_range": sum(ranges) / len(ranges),
        "average_z": average("z"), "min_z": min(point["z"] for point in points),
        "max_z": max(point["z"] for point in points),
        "average_snr": average("snr"), "average_noise": average("noise"),
        "average_doppler": average("doppler"),
    }


def persistence_statistics(history):
    if not history:
        return 0.0, float("nan"), 0.0
    presence = sum(item["point_count"] > 0 for item in history) / float(len(history))
    nearest = [item["nearest_range"] for item in history
               if math.isfinite(item["nearest_range"])]
    voxel_counts = [item["voxel_count"] for item in history]
    return (presence, statistics.median(nearest) if nearest else float("nan"),
            float(statistics.median(voxel_counts)))


def risk_score(presence, nearest_range, median_voxels, min_range, max_range,
               density_saturation, weights):
    if density_saturation <= 0 or not min_range < max_range:
        raise ValueError("invalid risk normalization parameter")
    if len(weights) != 3 or any(weight < 0 for weight in weights) or sum(weights) <= 0:
        raise ValueError("risk weights must be nonnegative and have a positive sum")
    normalized = [weight / sum(weights) for weight in weights]
    distance = (0.0 if not math.isfinite(nearest_range) else
                max(0.0, min(1.0, (max_range - nearest_range) /
                             (max_range - min_range))))
    density = max(0.0, min(1.0, median_voxels / density_saturation))
    risk = normalized[0] * presence + normalized[1] * distance + normalized[2] * density
    return max(0.0, min(1.0, risk)), distance, density, tuple(normalized)


def recommended_sector(risks, nearest_ranges, occupied, minimum_clear_count=1):
    count = len(risks)
    if not (count and len(nearest_ranges) == count and len(occupied) == count):
        raise ValueError("sector arrays must be nonempty and equal length")
    clear = [index for index in range(count) if not occupied[index]]
    if len(clear) < minimum_clear_count:
        return None
    center = count // 2
    if center in clear:
        return center
    def ranking(index):
        nearest = nearest_ranges[index]
        far_preference = -(nearest if math.isfinite(nearest) else float("inf"))
        return (abs(index - center), risks[index], far_preference, index)
    return min(clear, key=ranking)


def find_clear_runs(risks, nearest_ranges, occupied, bounds):
    """Describe contiguous clear-sector runs in left-to-right sector order."""
    count = len(risks)
    if not (count and len(nearest_ranges) == count and
            len(occupied) == count and len(bounds) == count):
        raise ValueError("sector arrays must be nonempty and equal length")
    center_sector = count // 2
    runs = []
    index = 0
    while index < count:
        if occupied[index]:
            index += 1
            continue
        start = index
        while index + 1 < count and not occupied[index + 1]:
            index += 1
        end = index
        run_risks = [float(value) for value in risks[start:end + 1]]
        finite_nearest = [float(value) for value in nearest_ranges[start:end + 1]
                          if math.isfinite(value)]
        start_angle = float(bounds[start][0])
        end_angle = float(bounds[end][1])
        runs.append({
            "start_index": start,
            "end_index": end,
            "sector_count": end - start + 1,
            "start_angle_rad": start_angle,
            "end_angle_rad": end_angle,
            "center_angle_rad": 0.5 * (start_angle + end_angle),
            "angular_width_rad": abs(start_angle - end_angle),
            "mean_risk": sum(run_risks) / len(run_risks),
            "max_risk": max(run_risks),
            "min_risk": min(run_risks),
            "nearest_ranges": tuple(float(value)
                                    for value in nearest_ranges[start:end + 1]),
            # Missing returns remain unknown; NaN is never treated as zero range.
            "min_nearest_range_m": (min(finite_nearest) if finite_nearest
                                    else float("nan")),
            "max_nearest_range_m": (max(finite_nearest) if finite_nearest
                                    else float("nan")),
            "contains_center_sector": start <= center_sector <= end,
        })
        index += 1
    return runs


def score_clear_run(run):
    """Return the deterministic selection key for a clear-sector run."""
    center_distance = abs(run["center_angle_rad"])
    nearest = run["min_nearest_range_m"]
    # A finite, farther nearest return wins the final tie. Unknown stays last.
    nearest_preference = -nearest if math.isfinite(nearest) else float("inf")
    return (0 if run["contains_center_sector"] else 1,
            center_distance,
            -run["sector_count"],
            run["mean_risk"],
            nearest_preference,
            run["start_index"])


def select_low_occupancy_corridor(risks, nearest_ranges, occupied, bounds,
                                  recommended_heading=float("nan")):
    """Select the preferred contiguous clear run without changing risk policy.

    The existing recommended heading is used as the corridor centerline only
    when it lies inside the selected run. Otherwise the run midpoint is used.
    """
    runs = find_clear_runs(risks, nearest_ranges, occupied, bounds)
    if not runs:
        return None
    selected = dict(min(runs, key=score_clear_run))
    lower = min(selected["start_angle_rad"], selected["end_angle_rad"])
    upper = max(selected["start_angle_rad"], selected["end_angle_rad"])
    heading_inside = (math.isfinite(recommended_heading) and
                      lower <= recommended_heading <= upper)
    selected["recommended_heading_rad"] = float(recommended_heading)
    selected["recommended_heading_inside"] = heading_inside
    selected["center_heading_rad"] = (float(recommended_heading)
                                      if heading_inside else
                                      selected["center_angle_rad"])
    return selected


def corridor_to_array(corridor):
    """Convert a selected corridor to the public Float32MultiArray layout."""
    if corridor is None:
        nan = float("nan")
        return [0.0, nan, nan, nan, nan, 0.0, nan, nan, nan, 0.0]
    return [
        1.0,
        corridor["start_angle_rad"],
        corridor["end_angle_rad"],
        corridor["center_heading_rad"],
        corridor["angular_width_rad"],
        float(corridor["sector_count"]),
        corridor["mean_risk"],
        corridor["max_risk"],
        corridor["min_nearest_range_m"],
        1.0 if corridor["contains_center_sector"] else 0.0,
    ]
