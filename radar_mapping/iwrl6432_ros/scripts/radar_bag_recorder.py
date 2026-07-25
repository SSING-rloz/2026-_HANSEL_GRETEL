#!/usr/bin/env python3
"""Safely record IWRL6432 radar topics and write experiment metadata."""

import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
import time

import rosgraph
import rosbag
import rospy
import yaml
from sensor_msgs.msg import LaserScan, PointCloud2


REQUIRED_TOPICS = {
    "/radar/points": PointCloud2,
    "/radar/scan": LaserScan,
}
OPTIONAL_TOPICS = (
    "/radar/current_pose",
    "/radar/map_points",
    "/radar/rviz_guides",
    "/imu/data",
)
ALWAYS_TOPICS = ("/tf", "/tf_static")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate live radar topics, record a rosbag, and create YAML metadata."
    )
    parser.add_argument("experiment_name", help="Experiment label used in output filenames")
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser("~/iwrl6432_mapping_ws/bags"),
        help="Bag directory (default: ~/iwrl6432_mapping_ws/bags)",
    )
    parser.add_argument("--environment", default=None)
    parser.add_argument("--actual-translation-x-m", type=float, default=None)
    parser.add_argument("--actual-translation-y-m", type=float, default=None)
    parser.add_argument("--actual-rotation-deg", type=float, default=None)
    parser.add_argument("--sensor-height-m", type=float, default=None)
    parser.add_argument("--movement-duration-sec", type=float, default=None)
    parser.add_argument("--operator-notes", default=None)
    parser.add_argument(
        "--message-timeout", type=float, default=5.0,
        help="Seconds to wait for each required topic (default: 5)",
    )
    parser.add_argument(
        "--rate-window", type=float, default=3.0,
        help="Seconds used to measure required topic rates (default: 3)",
    )
    args = parser.parse_args(argv)
    if not args.experiment_name.strip():
        parser.error("experiment_name must not be empty")
    if any(ch in args.experiment_name for ch in "/\\\0"):
        parser.error("experiment_name must not contain '/', '\\', or NUL")
    if args.message_timeout <= 0 or args.rate_window <= 0:
        parser.error("--message-timeout and --rate-window must be positive")
    return args


def ensure_master():
    try:
        rosgraph.Master("/radar_bag_recorder").getPid()
    except Exception as exc:
        raise RuntimeError("ROS master에 연결할 수 없습니다: {}".format(exc))


def published_topic_names():
    try:
        return {name for name, _type in rospy.get_published_topics()}
    except rospy.ROSException as exc:
        raise RuntimeError("발행 토픽 목록을 읽지 못했습니다: {}".format(exc))


def verify_required_topics(timeout, rate_window):
    available = published_topic_names()
    missing = sorted(set(REQUIRED_TOPICS) - available)
    if missing:
        raise RuntimeError("필수 토픽이 없습니다: {}".format(", ".join(missing)))

    rates = {}
    for topic, msg_type in REQUIRED_TOPICS.items():
        try:
            rospy.wait_for_message(topic, msg_type, timeout=timeout)
        except rospy.ROSException:
            raise RuntimeError(
                "{} 토픽에서 {:.1f}초 안에 메시지를 받지 못했습니다".format(topic, timeout)
            )

        stamps = []

        def callback(_msg, sample_stamps=stamps):
            sample_stamps.append(time.monotonic())

        subscriber = rospy.Subscriber(topic, msg_type, callback, queue_size=100)
        deadline = time.monotonic() + rate_window
        while time.monotonic() < deadline and not rospy.is_shutdown():
            time.sleep(0.02)
        subscriber.unregister()
        if len(stamps) < 2:
            raise RuntimeError(
                "{} 발행 주기를 계산할 만큼 메시지가 충분하지 않습니다 ({}개)".format(
                    topic, len(stamps)
                )
            )
        elapsed = stamps[-1] - stamps[0]
        rates[topic] = (len(stamps) - 1) / elapsed if elapsed > 0 else 0.0
    return rates


def stop_recorder(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10.0)
        return
    except subprocess.TimeoutExpired:
        print("경고: SIGINT 후 종료되지 않아 SIGTERM을 보냅니다", file=sys.stderr)
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        print("오류: rosbag record가 SIGTERM 후에도 종료되지 않았습니다", file=sys.stderr)


def format_local(when):
    return when.astimezone().isoformat(timespec="seconds")


def write_metadata(path, args, bag_path, started, ended, topics, rates):
    size = os.path.getsize(bag_path) if os.path.exists(bag_path) else 0
    try:
        with rosbag.Bag(bag_path, "r") as bag:
            bag_duration = bag.get_end_time() - bag.get_start_time()
            actual_topics = sorted(bag.get_type_and_topic_info().topics)
    except rosbag.bag.ROSBagException as exc:
        raise RuntimeError("완료된 bag의 길이를 읽지 못했습니다: {}".format(exc))
    metadata = {
        "experiment_name": args.experiment_name,
        "bag_file": os.path.abspath(bag_path),
        "date": format_local(started),
        "environment": args.environment,
        "actual_translation_x_m": args.actual_translation_x_m,
        "actual_translation_y_m": args.actual_translation_y_m,
        "actual_rotation_deg": args.actual_rotation_deg,
        "sensor_height_m": args.sensor_height_m,
        "movement_duration_sec": args.movement_duration_sec,
        "operator_notes": args.operator_notes,
        "radar_model": "IWRL6432BOOST",
        "sdk_version": "05.05.04.02",
        "ros_distribution": "noetic",
        "recorded_topics": actual_topics,
        "point_topic_hz": round(rates["/radar/points"], 3),
        "scan_topic_hz": round(rates["/radar/scan"], 3),
        "bag_duration_sec": round(max(0.0, bag_duration), 3),
        "bag_size_bytes": size,
    }
    with open(path, "w", encoding="utf-8") as stream:
        yaml.safe_dump(metadata, stream, allow_unicode=True, sort_keys=False)
    return actual_topics


def main(argv=None):
    args = parse_args(argv)
    process = None
    stopping = False

    def request_stop(signum, _frame):
        nonlocal stopping
        if not stopping:
            stopping = True
            print("종료 신호 {} 수신: rosbag을 정상 종료합니다".format(signum))
            stop_recorder(process)

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        ensure_master()
        rospy.init_node("radar_bag_recorder", anonymous=True, disable_signals=True)
        rospy.on_shutdown(lambda: stop_recorder(process))
        rates = verify_required_topics(args.message_timeout, args.rate_window)
        available = published_topic_names()
        topics = list(REQUIRED_TOPICS) + list(ALWAYS_TOPICS)
        topics.extend(topic for topic in OPTIONAL_TOPICS if topic in available)
        print("필수 토픽 확인 완료")
        print("  /radar/points: {:.3f} Hz".format(rates["/radar/points"]))
        print("  /radar/scan: {:.3f} Hz".format(rates["/radar/scan"]))

        output_dir = os.path.abspath(os.path.expanduser(args.output_dir))
        os.makedirs(output_dir, exist_ok=True)
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bag_path = os.path.join(output_dir, "{}_{}.bag".format(args.experiment_name, timestamp))
        yaml_path = os.path.splitext(bag_path)[0] + ".yaml"
        command = ["rosbag", "record", "-O", bag_path] + topics
        started = dt.datetime.now().astimezone()
        process = subprocess.Popen(command)
        print("기록 시작: {}".format(bag_path))
        while process.poll() is None and not stopping and not rospy.is_shutdown():
            time.sleep(0.1)
        stop_recorder(process)
        ended = dt.datetime.now().astimezone()

        if not os.path.isfile(bag_path):
            raise RuntimeError("완료된 bag 파일이 생성되지 않았습니다")
        active_path = bag_path + ".active"
        if os.path.exists(active_path):
            raise RuntimeError("미완료 .active 파일이 남았습니다: {}".format(active_path))
        actual_topics = write_metadata(yaml_path, args, bag_path, started, ended, topics, rates)
        duration = (ended - started).total_seconds()
        print("기록 완료")
        print("  bag 전체 경로: {}".format(bag_path))
        print("  시작 시각: {}".format(format_local(started)))
        print("  종료 시각: {}".format(format_local(ended)))
        print("  기록 시간: {:.3f}초".format(duration))
        print("  파일 크기: {} bytes".format(os.path.getsize(bag_path)))
        print("  실제 기록 토픽: {}".format(", ".join(actual_topics)))
        print("  메타데이터: {}".format(yaml_path))
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        stop_recorder(process)
        print("오류: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
