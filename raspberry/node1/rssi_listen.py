#!/usr/bin/env python3

import argparse
import csv
import datetime
import json
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def now_kst_string():
    """한국 기준 현재 시각 문자열"""
    return datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def run_cmd(cmd):
    """명령어 실행 후 stdout 반환"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1.5
        )

        if result.returncode != 0:
            return ""

        return result.stdout

    except Exception:
        return ""


def read_client_rssi(interface):
    """
    client 인터페이스 RSSI 읽기.

    내부 실행:
        iw dev wlan0 link

    의미:
        이 노드가 연결된 AP/상위 노드로부터 수신하는 RSSI
    """
    output = run_cmd(["iw", "dev", interface, "link"])

    row_list = []

    if not output or "Not connected" in output:
        return row_list

    peer_mac = ""
    signal_dbm = ""

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Connected to"):
            parts = line.split()
            if len(parts) >= 3:
                peer_mac = parts[2]

        elif line.startswith("signal:"):
            match = re.search(r"signal:\s*(-?\d+)", line)
            if match:
                signal_dbm = match.group(1)

    if signal_dbm != "":
        row_list.append({
            "source": "client_link",
            "interface": interface,
            "peer_mac": peer_mac,
            "rssi_dbm": signal_dbm,
            "rssi_avg_dbm": ""
        })

    return row_list


def read_ap_rssi(interface):
    """
    AP 인터페이스 RSSI 읽기.

    내부 실행:
        iw dev uap0 station dump

    의미:
        이 노드의 AP에 붙은 하위 노드들이 보내는 신호를
        이 노드가 수신한 RSSI
    """
    output = run_cmd(["iw", "dev", interface, "station", "dump"])

    row_list = []

    if not output:
        return row_list

    current_mac = ""
    current_signal = ""
    current_signal_avg = ""

    def flush_station():
        if current_mac and current_signal:
            row_list.append({
                "source": "ap_station",
                "interface": interface,
                "peer_mac": current_mac,
                "rssi_dbm": current_signal,
                "rssi_avg_dbm": current_signal_avg
            })

    for line in output.splitlines():
        line = line.strip()

        if line.startswith("Station "):
            flush_station()

            parts = line.split()
            current_mac = parts[1] if len(parts) >= 2 else ""
            current_signal = ""
            current_signal_avg = ""

        elif line.startswith("signal avg:"):
            match = re.search(r"signal avg:\s*(-?\d+)", line)
            if match:
                current_signal_avg = match.group(1)

        elif line.startswith("signal:"):
            match = re.search(r"signal:\s*(-?\d+)", line)
            if match:
                current_signal = match.group(1)

    flush_station()

    return row_list


class RSSILogger:
    def __init__(self, node_name, client_interfaces, ap_interfaces, log_dir):
        self.node_name = node_name
        self.client_interfaces = client_interfaces
        self.ap_interfaces = ap_interfaces
        self.log_dir = Path(log_dir)

        self.stop_event = threading.Event()
        self.thread = None

    def start(self, experiment_id, interval, duration):
        """RSSI 로깅 시작"""
        self.stop()

        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._worker,
            args=(experiment_id, interval, duration),
            daemon=True
        )
        self.thread.start()

    def stop(self):
        """RSSI 로깅 중단"""
        if self.thread is not None and self.thread.is_alive():
            self.stop_event.set()
            self.thread.join(timeout=2)

    def _create_csv(self, experiment_id):
        """CSV 파일 생성"""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        file_time = datetime.datetime.now(KST).strftime("%Y%m%d_%H%M%S")
        csv_path = self.log_dir / f"{experiment_id}_{self.node_name}_{file_time}.csv"

        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "time_kst",
                    "experiment_id",
                    "node_name",
                    "source",
                    "interface",
                    "peer_mac",
                    "rssi_dbm",
                    "rssi_avg_dbm"
                ]
            )
            writer.writeheader()

        return csv_path

    def _write_rows(self, csv_path, experiment_id, rssi_rows):
        """RSSI row들을 CSV에 저장"""
        with open(csv_path, "a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "time_kst",
                    "experiment_id",
                    "node_name",
                    "source",
                    "interface",
                    "peer_mac",
                    "rssi_dbm",
                    "rssi_avg_dbm"
                ]
            )

            for rssi in rssi_rows:
                writer.writerow({
                    "time_kst": now_kst_string(),
                    "experiment_id": experiment_id,
                    "node_name": self.node_name,
                    "source": rssi["source"],
                    "interface": rssi["interface"],
                    "peer_mac": rssi["peer_mac"],
                    "rssi_dbm": rssi["rssi_dbm"],
                    "rssi_avg_dbm": rssi["rssi_avg_dbm"]
                })

    def _collect_rssi(self):
        """설정된 인터페이스들의 RSSI만 수집"""
        rows = []

        for interface in self.client_interfaces:
            rows.extend(read_client_rssi(interface))

        for interface in self.ap_interfaces:
            rows.extend(read_ap_rssi(interface))

        return rows

    def _worker(self, experiment_id, interval, duration):
        """로깅 스레드 본체"""
        csv_path = self._create_csv(experiment_id)

        print(f"[INFO] logging started: {csv_path}")

        start_time = time.time()
        end_time = start_time + duration

        while not self.stop_event.is_set():
            if time.time() >= end_time:
                break

            rssi_rows = self._collect_rssi()
            self._write_rows(csv_path, experiment_id, rssi_rows)

            for row in rssi_rows:
                print(
                    f"[RSSI] {now_kst_string()} | "
                    f"{self.node_name} | "
                    f"{row['source']} | "
                    f"{row['interface']} | "
                    f"peer={row['peer_mac']} | "
                    f"RSSI={row['rssi_dbm']} dBm"
                )

            time.sleep(interval)

        print("[INFO] logging stopped")


def parse_command(data):
    """
    UDP 명령 파싱.

    지원:
        START
        STOP

    또는 JSON:
        {"cmd":"START","experiment_id":"test01","duration":60,"interval":1}
        {"cmd":"STOP"}
    """
    text = data.decode("utf-8", errors="ignore").strip()

    try:
        msg = json.loads(text)
        cmd = msg.get("cmd", "").upper()
        return cmd, msg

    except json.JSONDecodeError:
        return text.upper(), {}


def udp_server(logger, listen_ip, listen_port, default_duration, default_interval):
    """UDP 포트에서 START / STOP 명령 대기"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((listen_ip, listen_port))

    print(f"[INFO] waiting UDP command on {listen_ip}:{listen_port}")

    while True:
        data, sender = sock.recvfrom(4096)
        cmd, msg = parse_command(data)

        print(f"[INFO] command from {sender}: {data.decode('utf-8', errors='ignore').strip()}")

        if cmd == "START":
            experiment_id = msg.get(
                "experiment_id",
                datetime.datetime.now(KST).strftime("exp_%Y%m%d_%H%M%S")
            )
            duration = float(msg.get("duration", default_duration))
            interval = float(msg.get("interval", default_interval))

            logger.start(
                experiment_id=experiment_id,
                interval=interval,
                duration=duration
            )

        elif cmd == "STOP":
            logger.stop()

        else:
            print("[WARN] unknown command")


def main():
    parser = argparse.ArgumentParser(
        description="Simple UDP-triggered RSSI logger"
    )

    parser.add_argument("--node-name", required=True)
    parser.add_argument("--listen-ip", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=5005)

    parser.add_argument(
        "--client-if",
        action="append",
        default=[],
        help="client interface to log, e.g. wlan0"
    )

    parser.add_argument(
        "--ap-if",
        action="append",
        default=[],
        help="AP interface to log, e.g. uap0"
    )

    parser.add_argument("--log-dir", default="./rssi_logs")
    parser.add_argument("--default-duration", type=float, default=60)
    parser.add_argument("--default-interval", type=float, default=1)

    args = parser.parse_args()

    logger = RSSILogger(
        node_name=args.node_name,
        client_interfaces=args.client_if,
        ap_interfaces=args.ap_if,
        log_dir=args.log_dir
    )

    try:
        udp_server(
            logger=logger,
            listen_ip=args.listen_ip,
            listen_port=args.listen_port,
            default_duration=args.default_duration,
            default_interval=args.default_interval
        )

    except KeyboardInterrupt:
        logger.stop()
        print("\n[INFO] terminated")


if __name__ == "__main__":
    main()