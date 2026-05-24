#!/usr/bin/env python3

import argparse
import re
import sys
from typing import Optional, TextIO, Tuple, Union


STATION_RE = re.compile(r"\bstation=([0-9a-fA-F:]{17})\b")
RAW_RE = re.compile(r"\braw_dbm=(-?\d+)\b")
EWMA_RE = re.compile(r"\bewma_dbm=(-?\d+(?:\.\d+)?)\b")


ParsedReading = Tuple[str, int, float]
ParsedStatus = Tuple[str, str]
ParsedLine = Optional[Union[ParsedReading, ParsedStatus]]


def parse_line(line: str) -> ParsedLine:
    line = line.strip()

    if not line:
        return None

    if line.startswith("status=no_stations_connected"):
        return ("status", line)

    station_match = STATION_RE.search(line)
    raw_match = RAW_RE.search(line)
    ewma_match = EWMA_RE.search(line)

    if not station_match or not raw_match or not ewma_match:
        raise ValueError(f"unrecognized input line: {line}")

    station = station_match.group(1).lower()
    raw_dbm = int(raw_match.group(1))
    ewma_dbm = float(ewma_match.group(1))

    return (station, raw_dbm, ewma_dbm)


def classify_link(ewma_dbm: float, threshold: float) -> str:
    if ewma_dbm <= threshold:
        return "link_degraded"

    return "link_ok"


def process_stream(stream: TextIO, threshold: float) -> None:
    for line_no, line in enumerate(stream, start=1):
        try:
            parsed = parse_line(line)
        except ValueError as exc:
            print(f"warning=line_parse_failed line_no={line_no} detail={exc}", file=sys.stderr)
            continue

        if parsed is None:
            continue

        key = parsed[0]

        if key == "status":
            print(parsed[1])
            continue

        station, raw_dbm, ewma_dbm = parsed
        status = classify_link(ewma_dbm, threshold)

        print(
            f"station={station} "
            f"raw_dbm={raw_dbm} "
            f"ewma_dbm={ewma_dbm:.2f} "
            f"threshold_dbm={threshold:.2f} "
            f"status={status}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify station link quality from EWMA RSSI readings."
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=-70.0,
        help="RSSI threshold in dBm. ewma_dbm <= threshold means link_degraded. Default: -70.0",
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
        process_stream(sys.stdin, args.threshold)
        return 0

    try:
        with open(args.input, "r", encoding="utf-8") as stream:
            process_stream(stream, args.threshold)
    except OSError as exc:
        print(f"error=input_open_failed path={args.input} detail={exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())