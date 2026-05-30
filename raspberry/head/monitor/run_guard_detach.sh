#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - monitor + auto-detach runner
#
# This is the INTEGRATED pipeline used for boot automation. It runs the
# existing monitor-only pipeline (run_monitor.sh) and pipes its guard output
# into detach_bridge.py, which actually triggers detach over the control
# channel (UDP 5000, command "detach_press").
#
#   run_monitor.sh  (rssi_reader -> link_filter -> link_watch -> link_guard)
#        |  stdout: station=<MAC> ... guard_status=detach_candidate
#        v
#   detach_bridge.py  --station-map station_map.conf
#        |  UDP "detach_press" -> <node_ip>:5000  (on fresh candidate only)
#
# run_monitor.sh itself stays monitor-only; this wrapper is what adds the
# control action. Any options passed to this script are forwarded to
# run_monitor.sh (e.g. --iface, --threshold, --degraded-count, --log).
#
# Use --bridge-dry-run to observe decisions without sending UDP.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RUN_MONITOR="$SCRIPT_DIR/run_monitor.sh"
DETACH_BRIDGE="$SCRIPT_DIR/detach_bridge.py"
STATION_MAP="$SCRIPT_DIR/station_map.conf"

BRIDGE_DRY_RUN=""
# Persistent latch state file. Default matches detach_bridge.py's built-in
# default; expose it here so a custom path can flow through to the bridge.
STATE_FILE="/var/lib/hansel/detach_state.json"
MONITOR_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bridge-dry-run)
            BRIDGE_DRY_RUN="--dry-run"
            shift
            ;;
        --station-map)
            STATION_MAP="${2:-}"
            shift 2
            ;;
        --state-file)
            STATE_FILE="${2:-}"
            shift 2
            ;;
        *)
            MONITOR_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ ! -f "$RUN_MONITOR" ]]; then
    echo "[run_guard_detach] ERROR: missing $RUN_MONITOR" >&2
    exit 1
fi
if [[ ! -f "$DETACH_BRIDGE" ]]; then
    echo "[run_guard_detach] ERROR: missing $DETACH_BRIDGE" >&2
    exit 1
fi

echo "[run_guard_detach] starting monitor pipeline + detach bridge" >&2
echo "[run_guard_detach] station_map=$STATION_MAP state_file=$STATE_FILE dry_run=${BRIDGE_DRY_RUN:-no}" >&2

bash "$RUN_MONITOR" "${MONITOR_ARGS[@]}" \
    | python3 -u "$DETACH_BRIDGE" --station-map "$STATION_MAP" --state-file "$STATE_FILE" $BRIDGE_DRY_RUN
