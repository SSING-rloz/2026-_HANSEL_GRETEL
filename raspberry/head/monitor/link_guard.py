#!/usr/bin/env python3

import argparse
import re
import sys
from typing import Dict, Optional, TextIO, Tuple, Union


STATION_RE = re.compile(r"\bstation=([0-9a-fA-F:]{17})\b")
RAW_RE = re.compile(r"\braw_dbm=(-?\d+)\b")
EWMA_RE = re.compile(r"\bewma_dbm=(-?\d+(?:\.\d+)?)\b")
THRESHOLD_RE = re.compile(r"\bthreshold_dbm=(-?\d+(?:\.\d+)?)\b")
STATUS_RE = re.compile(r"\bstatus=(link_degraded|link_ok)\b")
INTERFACE_RE = re.compile(r"\binterface=([A-Za-z0-9_.:-]+)\b")


ParsedReading = Tuple[str, int, float, float, str]
ParsedStatus = Tuple[str, str]
ParsedLine = Optional[Union[ParsedReading, ParsedStatus]]

GuardState = Dict[str, Dict[str, int]]


def parse_line(line: str) -> ParsedLine:
    line = line.strip()

    if not line:
        return None

    if line.startswith("status=no_stations_connected"):
        interface_match = INTERFACE_RE.search(line)
        interface = interface_match.group(1) if interface_match else "unknown"
        return ("status", f"status=no_stations_connected interface={interface}")

    station_match = STATION_RE.search(line)
    raw_match = RAW_RE.search(line)
    ewma_match = EWMA_RE.search(line)
    threshold_match = THRESHOLD_RE.search(line)
    status_match = STATUS_RE.search(line)

    if not station_match or not raw_match or not ewma_match or not threshold_match or not status_match:
        raise ValueError(f"unrecognized input line: {line}")

    station = station_match.group(1).lower()
    raw_dbm = int(raw_match.group(1))
    ewma_dbm = float(ewma_match.group(1))
    threshold_dbm = float(threshold_match.group(1))
    status = status_match.group(1)

    return (station, raw_dbm, ewma_dbm, threshold_dbm, status)


def classify_guard_status(
    degraded_count: int,
    ok_count: int,
    degraded_limit: int,
    recover_limit: int,
) -> str:
    if degraded_count >= degraded_limit:
        return "detach_candidate"

    if ok_count >= recover_limit:
        return "recovered"

    return "watching"


def update_guard_state(
    station: str,
    status: str,
    state: GuardState,
    degraded_limit: int,
    recover_limit: int,
) -> Tuple[int, int, str]:
    degraded_count_by_station = state["degraded_count_by_station"]
    ok_count_by_station = state["ok_count_by_station"]

    if status == "link_degraded":
        degraded_count = degraded_count_by_station.get(station, 0) + 1
        ok_count = 0
    elif status == "link_ok":
        degraded_count = 0
        ok_count = ok_count_by_station.get(station, 0) + 1
    else:
        raise ValueError(f"unsupported status: {status}")

    degraded_count_by_station[station] = degraded_count
    ok_count_by_station[station] = ok_count

    guard_status = classify_guard_status(
        degraded_count,
        ok_count,
        degraded_limit,
        recover_limit,
    )

    return degraded_count, ok_count, guard_status


def process_stream(stream: TextIO, args: argparse.Namespace) -> None:
    state: GuardState = {
        "degraded_count_by_station": {},
        "ok_count_by_station": {},
    }

    for line_no, line in enumerate(stream, start=1):
        try:
            parsed = parse_line(line)
        except ValueError as exc:
            print(f"warning=line_parse_failed line_no={line_no} detail={exc}", file=sys.stderr)
            continue

        if parsed is None:
            continue

        if parsed[0] == "status":
            print(f"{parsed[1]} guard_status=no_stations")
            continue

        station, raw_dbm, ewma_dbm, threshold_dbm, status = parsed

        degraded_count, ok_count, guard_status = update_guard_state(
            station=station,
            status=status,
            state=state,
            degraded_limit=args.degraded_count,
            recover_limit=args.recover_count,
        )

        degraded_seconds = degraded_count * args.sample_interval
        ok_seconds = ok_count * args.sample_interval

        print(
            f"station={station} "
            f"raw_dbm={raw_dbm} "
            f"ewma_dbm={ewma_dbm:.2f} "
            f"threshold_dbm={threshold_dbm:.2f} "
            f"status={status} "
            f"degraded_count={degraded_count} "
            f"ok_count={ok_count} "
            f"degraded_seconds={degraded_seconds:.2f} "
            f"ok_seconds={ok_seconds:.2f} "
            f"guard_status={guard_status}"
        )


def positive_int(value: str) -> int:
    parsed = int(value)

    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be an integer >= 1")

    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)

    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be a positive float")

    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track consecutive link degradation and recovery events per station."
    )

    parser.add_argument(
        "--degraded-count",
        type=positive_int,
        default=10,
        help="Consecutive link_degraded samples required for detach_candidate. Default: 10",
    )

    parser.add_argument(
        "--recover-count",
        type=positive_int,
        default=6,
        help="Consecutive link_ok samples required for recovered. Default: 6",
    )

    parser.add_argument(
        "--sample-interval",
        type=positive_float,
        default=0.2,
        help="Expected sampling interval in seconds. Default: 0.2",
    )

    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input file path. If omitted, read from stdin.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.input is None:
        process_stream(sys.stdin, args)
        return 0

    try:
        with open(args.input, "r", encoding="utf-8") as stream:
            process_stream(stream, args)
    except OSError as exc:
        print(f"error=input_open_failed path={args.input} detail={exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())