#!/usr/bin/env python3
"""Inspect radar rosbag quality for later radar-odometry development.

Verdict policy:
* FAIL: required radar topic missing, duration < 3 s, no messages, or > 80% of
  PointCloud2 frames are empty.
* WARNING: temporary > 1 s data gap, any run of three empty scans, or sparse
  but continuous point data (mean width < 5).
* PASS: required data is present and none of the above conditions applies.
"""

import argparse
import math
import os
import sys

import rosbag


POINT_TOPIC = "/radar/points"
SCAN_TOPIC = "/radar/scan"
REQUIRED_TOPICS = (POINT_TOPIC, SCAN_TOPIC)
LONG_GAP_SEC = 1.0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Inspect a radar rosbag and judge odometry usability.")
    parser.add_argument("bag", help="Path to a .bag file")
    return parser.parse_args(argv)


def hz(count, first, last):
    return (count - 1) / (last - first) if count >= 2 and last > first else 0.0


def inspect(path):
    if not os.path.isfile(path):
        raise RuntimeError("bag 파일이 존재하지 않습니다: {}".format(path))

    topic_counts = {}
    topic_first = {}
    topic_last = {}
    previous_time = {}
    long_gaps = []
    point_widths = []
    scan_finite_counts = []
    consecutive_empty_scans = 0
    empty_scan_run = False
    total_messages = 0
    start = None
    end = None

    try:
        with rosbag.Bag(path, "r") as bag:
            for topic, msg, stamp in bag.read_messages():
                now = stamp.to_sec()
                total_messages += 1
                start = now if start is None else min(start, now)
                end = now if end is None else max(end, now)
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
                topic_first.setdefault(topic, now)
                topic_last[topic] = now
                if (
                    topic in REQUIRED_TOPICS
                    and topic in previous_time
                    and now - previous_time[topic] > LONG_GAP_SEC
                ):
                    long_gaps.append((topic, previous_time[topic], now, now - previous_time[topic]))
                previous_time[topic] = now

                if topic == POINT_TOPIC:
                    point_widths.append(int(msg.width))
                elif topic == SCAN_TOPIC:
                    finite_count = sum(1 for value in msg.ranges if math.isfinite(value))
                    scan_finite_counts.append(finite_count)
                    if finite_count == 0:
                        consecutive_empty_scans += 1
                        if consecutive_empty_scans >= 3:
                            empty_scan_run = True
                    else:
                        consecutive_empty_scans = 0
    except rosbag.bag.ROSBagException as exc:
        raise RuntimeError("bag을 열거나 읽지 못했습니다: {}".format(exc))

    if total_messages == 0:
        raise RuntimeError("bag이 비어 있습니다 (메시지 0개)")

    duration = max(0.0, end - start)
    missing = [topic for topic in REQUIRED_TOPICS if topic_counts.get(topic, 0) == 0]
    empty_points = sum(1 for width in point_widths if width == 0)
    empty_ratio = empty_points / len(point_widths) if point_widths else 1.0
    point_avg = sum(point_widths) / len(point_widths) if point_widths else 0.0
    scan_avg = sum(scan_finite_counts) / len(scan_finite_counts) if scan_finite_counts else 0.0

    failures = []
    warnings = []
    if missing:
        failures.append("필수 토픽 누락: {}".format(", ".join(missing)))
    if duration < 3.0:
        failures.append("전체 길이가 3초 미만 ({:.3f}초)".format(duration))
    if empty_ratio > 0.8:
        failures.append("PointCloud2 빈 프레임 비율이 80% 초과 ({:.1%})".format(empty_ratio))
    if long_gaps:
        warnings.append("1초를 초과하는 메시지 공백 {}개".format(len(long_gaps)))
    if empty_scan_run:
        warnings.append("유효 scan이 없는 프레임이 3회 이상 연속됨")
    if point_widths and 0 < point_avg < 5:
        warnings.append("포인트가 적지만 연속적으로 존재 (평균 width {:.2f})".format(point_avg))

    verdict = "FAIL" if failures else ("WARNING" if warnings else "PASS")
    reasons = failures + warnings
    if not reasons:
        reasons = ["필수 데이터가 충분하고 장시간 공백이 없음"]

    print("bag: {}".format(os.path.abspath(path)))
    print("시작 시각(Unix): {:.6f}".format(start))
    print("종료 시각(Unix): {:.6f}".format(end))
    print("전체 길이: {:.3f} sec".format(duration))
    print("전체 메시지 수: {}".format(total_messages))
    print("토픽별 통계:")
    for topic in sorted(topic_counts):
        rate = hz(topic_counts[topic], topic_first[topic], topic_last[topic])
        print("  {}: {} messages, {:.3f} Hz".format(topic, topic_counts[topic], rate))
    print("/radar/points 평균 width: {:.3f}".format(point_avg))
    print("/radar/points 최소 width: {}".format(min(point_widths) if point_widths else 0))
    print("/radar/points 최대 width: {}".format(max(point_widths) if point_widths else 0))
    print("빈 PointCloud2 프레임 비율: {:.3%}".format(empty_ratio))
    print("/radar/scan 메시지 수: {}".format(len(scan_finite_counts)))
    print("finite range 평균: {:.3f}".format(scan_avg))
    print("finite range 최소: {}".format(min(scan_finite_counts) if scan_finite_counts else 0))
    print("finite range 최대: {}".format(max(scan_finite_counts) if scan_finite_counts else 0))
    print("유효 scan이 전혀 없는 구간: {}".format("있음" if empty_scan_run else "없음"))
    print("/tf 포함: {}".format("예" if topic_counts.get("/tf", 0) else "아니요"))
    print("/tf_static 포함: {}".format("예" if topic_counts.get("/tf_static", 0) else "아니요"))
    print("메시지 간 1초 초과 공백: {}".format("있음" if long_gaps else "없음"))
    for topic, gap_start, gap_end, gap in long_gaps[:20]:
        print("  {}: {:.3f}s ({:.6f} -> {:.6f})".format(topic, gap, gap_start, gap_end))
    print("자동 radar odometry 데이터 사용 가능 판정: {}".format(verdict))
    for reason in reasons:
        print("  - {}".format(reason))
    return verdict


def main(argv=None):
    args = parse_args(argv)
    try:
        inspect(os.path.abspath(os.path.expanduser(args.bag)))
        return 0
    except (RuntimeError, OSError) as exc:
        print("오류: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
