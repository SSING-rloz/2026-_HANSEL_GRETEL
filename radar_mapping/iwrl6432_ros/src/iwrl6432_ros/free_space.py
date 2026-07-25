"""Pure geometry and grid helpers for sparse-radar local free-space detection."""

import math


def bin_count(min_angle_deg, max_angle_deg, angle_bin_deg):
    return int(math.floor((max_angle_deg - min_angle_deg) / angle_bin_deg + 1e-9)) + 1


def bin_angles(min_angle_deg, max_angle_deg, angle_bin_deg):
    return [min(max_angle_deg, min_angle_deg + index * angle_bin_deg)
            for index in range(bin_count(min_angle_deg, max_angle_deg, angle_bin_deg))]


def nearest_ranges(points, min_range, max_range, min_angle, max_angle,
                   angle_bin, min_snr, min_z, max_z):
    """Return nearest measured range per angular bin; None means unobserved."""
    result = [None] * bin_count(min_angle, max_angle, angle_bin)
    for point in points:
        x_value, y_value, z_value = point[:3]
        snr = point[3] if len(point) > 3 else float("inf")
        radius = math.hypot(x_value, y_value)
        angle = math.degrees(math.atan2(y_value, x_value))
        if not (min_range <= radius <= max_range and min_z <= z_value <= max_z and
                snr >= min_snr and min_angle <= angle <= max_angle):
            continue
        index = int(math.floor((angle - min_angle) / angle_bin + 0.5))
        index = max(0, min(index, len(result) - 1))
        if result[index] is None or radius < result[index]:
            result[index] = radius
    return result


def merge_history(frames):
    if not frames:
        return []
    merged = [None] * len(frames[0])
    for frame in frames:
        for index, value in enumerate(frame):
            if value is not None and (merged[index] is None or value < merged[index]):
                merged[index] = value
    return merged


def interpolate_short_gaps(ranges, max_gap_bins, max_jump):
    """Fill only bounded short gaps whose endpoint ranges are mutually consistent."""
    output = list(ranges)
    observed = [index for index, value in enumerate(ranges) if value is not None]
    for left, right in zip(observed, observed[1:]):
        gap = right - left - 1
        if 0 < gap <= max_gap_bins and abs(ranges[right] - ranges[left]) <= max_jump:
            for step in range(1, gap + 1):
                fraction = step / float(gap + 1)
                output[left + step] = ranges[left] + fraction * (ranges[right] - ranges[left])
    return output


def contour_segments(ranges, angles_deg, max_jump):
    """Return independent adjacent line segments without bridging distant returns."""
    segments = []
    for index in range(len(ranges) - 1):
        first, second = ranges[index], ranges[index + 1]
        if first is None or second is None or abs(first - second) > max_jump:
            continue
        a0, a1 = math.radians(angles_deg[index]), math.radians(angles_deg[index + 1])
        segments.append(((first * math.cos(a0), first * math.sin(a0)),
                         (second * math.cos(a1), second * math.sin(a1))))
    return segments


def free_space_boundary(ranges, angles_deg, safety_margin, unknown_range):
    boundary = []
    for radius, angle_deg in zip(ranges, angles_deg):
        safe = unknown_range if radius is None else max(0.0, radius - safety_margin)
        angle = math.radians(angle_deg)
        boundary.append((safe * math.cos(angle), safe * math.sin(angle)))
    return boundary


def corridor_candidates(ranges, angles_deg, angle_bin_deg, min_clearance,
                        robot_width, clearance_margin, min_corridor_angle):
    """Find contiguous measured-clear sectors and score width, depth, and forward bias."""
    candidates = []
    start = None
    for index in range(len(ranges) + 1):
        clear = index < len(ranges) and ranges[index] is not None and ranges[index] >= min_clearance
        if clear and start is None:
            start = index
        if not clear and start is not None:
            end = index - 1
            span_deg = (end - start + 1) * angle_bin_deg
            minimum = min(ranges[start:end + 1])
            width = 2.0 * minimum * math.sin(math.radians(span_deg) / 2.0)
            required_width = robot_width + 2.0 * clearance_margin
            if span_deg >= min_corridor_angle and width >= required_width:
                center = 0.5 * (angles_deg[start] + angles_deg[end])
                # Width dominates, depth rewards distant obstacles, and a small
                # forward-bias term resolves otherwise similar left/right choices.
                score = width + 0.35 * minimum - 0.004 * abs(center)
                candidates.append({
                    "start_index": start, "end_index": end,
                    "start_angle_deg": angles_deg[start],
                    "end_angle_deg": angles_deg[end],
                    "center_angle_deg": center, "min_distance_m": minimum,
                    "width_m": width, "score": score,
                })
            start = None
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def make_occupancy(ranges, angles_deg, resolution, width_m, height_m,
                   sensor_x, sensor_y, obstacle_thickness, inflation_radius):
    width = int(round(width_m / resolution))
    height = int(round(height_m / resolution))
    origin_x = sensor_x - 0.5
    origin_y = sensor_y - height_m / 2.0
    data = [-1] * (width * height)

    def cell(x_value, y_value):
        gx = int(math.floor((x_value - origin_x) / resolution))
        gy = int(math.floor((y_value - origin_y) / resolution))
        return gx, gy

    def set_value(gx, gy, value):
        if 0 <= gx < width and 0 <= gy < height:
            position = gy * width + gx
            if value == 100 or data[position] != 100:
                data[position] = value

    for radius, angle_deg in zip(ranges, angles_deg):
        if radius is None:
            continue
        angle = math.radians(angle_deg)
        free_end = max(0.0, radius - obstacle_thickness * 0.5)
        steps = int(math.floor(free_end / (resolution * 0.5)))
        for step in range(steps + 1):
            distance = step * resolution * 0.5
            gx, gy = cell(sensor_x + distance * math.cos(angle),
                          sensor_y + distance * math.sin(angle))
            set_value(gx, gy, 0)

        obstacle_x = sensor_x + radius * math.cos(angle)
        obstacle_y = sensor_y + radius * math.sin(angle)
        occupied_radius = obstacle_thickness * 0.5 + inflation_radius
        cells = int(math.ceil(occupied_radius / resolution))
        center_x, center_y = cell(obstacle_x, obstacle_y)
        for dx in range(-cells, cells + 1):
            for dy in range(-cells, cells + 1):
                if math.hypot(dx * resolution, dy * resolution) <= occupied_radius + 1e-9:
                    set_value(center_x + dx, center_y + dy, 100)
    return width, height, origin_x, origin_y, data
