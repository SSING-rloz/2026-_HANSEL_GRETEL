#!/usr/bin/env python3

# HANSEL/GRETEL Head Pi - auto-detach bridge
#
# Role:
#   The ONLY component connecting the (monitor) decision layer to the (control)
#   execution layer. It is an external adapter: it does NOT modify any teammate
#   motor/GPIO/servo logic. It only uses the already-existing UDP command
#   interface of the node control servers.
#
# Input  (stdin):
#   The line-oriented stdout of link_guard.py, e.g.
#     station=aa:bb:cc:dd:ee:ff raw_dbm=-75 ewma_dbm=-73.40 threshold_dbm=-70.00 \
#       status=link_degraded degraded_count=10 ok_count=0 ... guard_status=detach_candidate
#   "station" is the wlan0 MAC of the degrading client = the node about to go
#   out of range = the node that must physically detach.
#
# Output (UDP):
#   On a fresh detach for a known, NOT-yet-latched station, send the text
#   command "detach_press" to that node's control server (<node_ip>:5000).
#   Node*_control.py maps "detach_press" -> detach_servo_press(), which is a
#   self-contained press->wait->rest cycle (no separate detach_rest needed).
#
# LATCH POLICY (one detach per node per mission):
#   Once a node is detached, it is LATCHED and will NOT be detached again for
#   the rest of the mission. We do NOT auto-rearm on guard_status=recovered:
#   a physically detached node must not be re-detached just because its RSSI
#   briefly recovers. The latch is persisted to a state file so that a service
#   restart or a Head reboot does NOT cause a second detach of an already
#   detached node. The latch is cleared only by an explicit pre-mission reset
#   (reset_detach_state.sh), never at runtime.
#
# IMPORTANT non-goals:
#   - keyboard.py is NOT the detach path. rssi_listen* is NOT used.
#   - The detach transport/port is the already-confirmed control channel
#     UDP 5000. No unconfirmed "guard 6000" trigger is invented.
#   - No human-in-the-loop approval step is added.

import argparse
import json
import os
import re
import socket
import sys
import time
from typing import Dict, Optional, Set, Tuple

STATION_RE = re.compile(r"\bstation=([0-9a-fA-F:]{17})\b")
GUARD_RE = re.compile(r"\bguard_status=([A-Za-z_]+)\b")

DEFAULT_STATE_FILE = "/var/lib/hansel/detach_state.json"


def load_station_map(path: str) -> Dict[str, Tuple[str, str]]:
    """Parse 'MAC IP NAME' lines into {mac_lower: (ip, name)}."""
    mapping: Dict[str, Tuple[str, str]] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    print(
                        f"warning=station_map_bad_line line_no={line_no} detail={line!r}",
                        file=sys.stderr,
                    )
                    continue
                mac = parts[0].lower()
                ip = parts[1]
                name = parts[2] if len(parts) >= 3 else mac
                mapping[mac] = (ip, name)
    except OSError as exc:
        print(f"error=station_map_open_failed path={path} detail={exc}", file=sys.stderr)
    return mapping


def load_latched(state_file: str) -> Set[str]:
    """Load the set of already-detached (latched) station MACs."""
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        latched = data.get("latched_stations", {})
        return {mac.lower() for mac in latched.keys()}
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as exc:
        print(f"warning=state_load_failed path={state_file} detail={exc}", file=sys.stderr)
        return set()


def persist_latched(state_file: str, latched_meta: Dict[str, dict]) -> None:
    """Write the latch set atomically. Failure is logged but non-fatal."""
    payload = {"latched_stations": latched_meta}
    try:
        directory = os.path.dirname(state_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = f"{state_file}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(tmp, state_file)
    except OSError as exc:
        print(
            f"warning=state_persist_failed path={state_file} detail={exc} "
            f"note=latch_still_held_in_memory",
            file=sys.stderr,
            flush=True,
        )


def parse_line(line: str) -> Optional[Tuple[Optional[str], str]]:
    """Return (station_or_None, guard_status) or None if not a guard line."""
    guard_match = GUARD_RE.search(line)
    if not guard_match:
        return None
    station_match = STATION_RE.search(line)
    station = station_match.group(1).lower() if station_match else None
    return (station, guard_match.group(1))


def send_detach(
    sock: socket.socket,
    ip: str,
    port: int,
    command: str,
    retry_count: int,
    retry_interval: float,
    dry_run: bool,
) -> None:
    """Send the detach command. Repeated identical detach_press is safe by
    code review (each is a complete press->rest cycle), so we resend it
    retry_count extra times to survive UDP loss. The node latch still ensures
    at most one detach EPISODE per node per mission."""
    total = 1 + max(0, retry_count)
    for attempt in range(1, total + 1):
        if dry_run:
            print(
                f"event=detach_dry_run target={ip}:{port} command={command} "
                f"attempt={attempt}/{total}",
                flush=True,
            )
        else:
            sock.sendto(command.encode("ascii"), (ip, port))
            print(
                f"event=detach_sent target={ip}:{port} command={command} "
                f"attempt={attempt}/{total}",
                flush=True,
            )
        if attempt < total and retry_interval > 0:
            time.sleep(retry_interval)


def process(stream, args, mapping: Dict[str, Tuple[str, str]]) -> None:
    # Latched stations survive across restarts via the state file.
    latched: Set[str] = load_latched(args.state_file)
    latched_meta: Dict[str, dict] = {}
    # In-memory only: stations we already warned about (unknown MAC) so we do
    # not spam the log. NOT persisted and NOT a latch (so filling the map and
    # restarting will let them fire).
    warned_unknown: Set[str] = set()

    print(
        f"event=bridge_start station_map_entries={len(mapping)} "
        f"preloaded_latched={len(latched)} state_file={args.state_file} "
        f"control_port={args.control_port} command={args.command} "
        f"retry_count={args.retry_count} retry_interval={args.retry_interval} "
        f"dry_run={args.dry_run}",
        flush=True,
    )

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for line in stream:
            parsed = parse_line(line)
            if parsed is None:
                continue
            station, guard_status = parsed

            if guard_status == "no_stations" or station is None:
                continue

            # recovered does NOT rearm. A latched (detached) node stays latched.
            if guard_status != "detach_candidate":
                continue

            if station in latched:
                # Already detached this mission; suppress everything.
                continue

            target = mapping.get(station)
            if target is None:
                if station not in warned_unknown:
                    print(
                        f"warning=unknown_station station={station} "
                        f"detail=not_in_station_map action=skip "
                        f"note=no_detach_sent_to_any_node",
                        file=sys.stderr,
                        flush=True,
                    )
                    warned_unknown.add(station)
                continue

            ip, name = target
            print(
                f"event=detach_candidate station={station} node={name} "
                f"target={ip}:{args.control_port}",
                flush=True,
            )
            send_detach(
                sock,
                ip,
                args.control_port,
                args.command,
                args.retry_count,
                args.retry_interval,
                args.dry_run,
            )
            # Latch immediately (even in dry-run, to exercise the same path).
            latched.add(station)
            latched_meta[station] = {
                "node": name,
                "ip": ip,
                "detached_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            persist_latched(args.state_file, latched_meta)
            print(f"event=latched station={station} node={name}", flush=True)
    finally:
        sock.close()


def positive_or_zero_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge link_guard detach_candidate events to UDP control detach_press."
    )
    parser.add_argument("--station-map", required=True, help="Path to MAC->IP[->name] map.")
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"Persistent latch state file. Default: {DEFAULT_STATE_FILE}",
    )
    parser.add_argument("--control-port", type=int, default=5000, help="Node control UDP port.")
    parser.add_argument("--command", default="detach_press", help="Detach command text.")
    parser.add_argument(
        "--retry-count",
        type=positive_or_zero_int,
        default=2,
        help="Extra resends of detach (safe; each is a full press cycle). Default: 2",
    )
    parser.add_argument(
        "--retry-interval",
        type=non_negative_float,
        default=0.2,
        help="Seconds between resends. Default: 0.2",
    )
    parser.add_argument("--dry-run", action="store_true", help="Log without sending UDP.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapping = load_station_map(args.station_map)
    process(sys.stdin, args, mapping)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
