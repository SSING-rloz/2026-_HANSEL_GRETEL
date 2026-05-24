#!/usr/bin/env python3

import argparse
import re
import sys
from typing import Optional, TextIO, Tuple


STATION_RE = re.compile(r"\bstation=([0-9a-fA-F:]{17})\b")
SIGNAL_RE = re.compile(r"\bsignal_dbm=(-?\d+)\b")
INTERFACE_RE = re.compile(r"\binterface=([A-Za-z0-9_.:-]+)\b")


ParsedRssi = Tuple[str, int]
ParsedStatus = Tuple[str, str]


def parse_line(line: str) -> Optional[ParsedRssi | ParsedStatus]:
    line = line.strip()

    if not line:
        return None

    if line.startswith("no_stations_connected"):
        match = INTERFACE_RE.search(line)
        interface = match.group(1) if match else "unknown"
        return ("status", f"status=no_stations_connected interface={interface}")

    station_match = STATION_RE.search(line)
    signal_match = SIGNAL_RE.search(line)

    if not station_match or not signal_match:
        raise ValueError(f"unrecognized input line: {line}")

    station = station_match.group(1).lower()
    signal_dbm = int(signal_match.group(1))

    return (station, signal_dbm)


def update_ewma(previous: Optional[float], current: int, alpha: float) -> float:
    if previous is None:
        return float(current)

    return alpha * current + (1.0 - alpha) * previous


def process_stream(stream: TextIO, alpha: float) -> None:
    ewma_by_station: dict[str, float] = {}

    for line_no, line in enumerate(stream, start=1):
        try:
            parsed = parse_line(line)
        except ValueError as exc:
            print(f"warning=line_parse_failed line_no={line_no} detail={exc}", file=sys.stderr)
            continue

        if parsed is None:
            continue

        key, value = parsed

        if key == "status":
            print(value)
            continue

        station = key
        raw_dbm = value

        previous = ewma_by_station.get(station)
        ewma = update_ewma(previous, raw_dbm, alpha)
        ewma_by_station[station] = ewma

        print(f"station={station} raw_dbm={raw_dbm} ewma_dbm={ewma:.2f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply station-level EWMA filtering to RSSI readings."
    )

    parser.add_argument(
        "--alpha",
        type=float,
        default=0.3,
        help="EWMA alpha value. Must satisfy 0 < alpha <= 1. Default: 0.3",
    )

    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input file path. If omitted, read from stdin.",
    )

    args = parser.parse_args()

    if not (0.0 < args.alpha <= 1.0):
        parser.error("--alpha must satisfy 0 < alpha <= 1")

    return args


def main() -> int:
    args = parse_args()

    if args.input is None:
        process_stream(sys.stdin, args.alpha)
        return 0

    try:
        with open(args.input, "r", encoding="utf-8") as stream:
            process_stream(stream, args.alpha)
    except OSError as exc:
        print(f"error=input_open_failed path={args.input} detail={exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())