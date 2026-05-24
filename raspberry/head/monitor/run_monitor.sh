#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - monitor pipeline runner
#
# Pipeline:
#   rssi_reader.sh -> link_filter.py -> link_watch.py -> link_guard.py
#
# Purpose:
#   Continuously read station RSSI values, smooth them with EWMA,
#   classify link quality, and emit guard-level candidate events.
#
# Important:
#   This script is monitor-only.
#   It does NOT start AP mode.
#   It does NOT stop AP mode.
#   It does NOT call detach_trigger.sh.
#   It does NOT call command_server.py.
#
# monitor layer:
#   detect / classify / emit candidate events
#
# control layer:
#   execute actual detach or motor commands later

IFACE="wlan0"
INTERVAL="0.2"
THRESHOLD="-70"
DEGRADED_COUNT="10"
RECOVER_COUNT="6"
ENABLE_LOG="false"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RSSI_READER="$SCRIPT_DIR/rssi_reader.sh"
LINK_FILTER="$SCRIPT_DIR/link_filter.py"
LINK_WATCH="$SCRIPT_DIR/link_watch.py"
LINK_GUARD="$SCRIPT_DIR/link_guard.py"

LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/monitor.log"

log() {
    echo "[run_monitor] $*" >&2
}

usage() {
    cat >&2 <<EOF
Usage:
  run_monitor.sh [options]

Options:
  --iface <name>             Wireless interface. Default: wlan0
  --interval <seconds>       Sampling interval. Default: 0.2
  --threshold <dBm>          RSSI threshold for link_watch.py. Default: -70
  --degraded-count <count>   Consecutive degraded samples for detach_candidate. Default: 10
  --recover-count <count>    Consecutive ok samples for recovered. Default: 6
  --log                      Also append final monitor output to logs/monitor.log
  -h, --help                 Show this help

Example pipeline behavior:
  rssi_reader.sh emits station=... signal_dbm=...
  link_filter.py emits station=... raw_dbm=... ewma_dbm=...
  link_watch.py emits station=... status=link_degraded/link_ok
  link_guard.py emits station=... guard_status=watching/detach_candidate/recovered

This script does not execute detach_trigger.sh.
EOF
}

is_positive_int() {
    [[ "$1" =~ ^[0-9]+$ ]] && [[ "$1" -ge 1 ]]
}

is_positive_float() {
    [[ "$1" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] && awk -v value="$1" 'BEGIN { exit !(value > 0) }'
}

is_float() {
    [[ "$1" =~ ^-?([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]]
}

require_file() {
    local file="$1"

    if [[ ! -f "$file" ]]; then
        log "ERROR: required file not found: $file"
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --iface)
            IFACE="${2:-}"
            if [[ -z "$IFACE" ]]; then
                log "ERROR: --iface requires a value"
                exit 1
            fi
            shift 2
            ;;

        --interval)
            INTERVAL="${2:-}"
            if ! is_positive_float "$INTERVAL"; then
                log "ERROR: --interval must be a positive number"
                exit 1
            fi
            shift 2
            ;;

        --threshold)
            THRESHOLD="${2:-}"
            if ! is_float "$THRESHOLD"; then
                log "ERROR: --threshold must be a number"
                exit 1
            fi
            shift 2
            ;;

        --degraded-count)
            DEGRADED_COUNT="${2:-}"
            if ! is_positive_int "$DEGRADED_COUNT"; then
                log "ERROR: --degraded-count must be an integer >= 1"
                exit 1
            fi
            shift 2
            ;;

        --recover-count)
            RECOVER_COUNT="${2:-}"
            if ! is_positive_int "$RECOVER_COUNT"; then
                log "ERROR: --recover-count must be an integer >= 1"
                exit 1
            fi
            shift 2
            ;;

        --log)
            ENABLE_LOG="true"
            shift
            ;;

        -h|--help)
            usage
            exit 0
            ;;

        *)
            log "ERROR: unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if ! command -v python3 >/dev/null 2>&1; then
    log "ERROR: python3 not found"
    exit 1
fi

if ! command -v awk >/dev/null 2>&1; then
    log "ERROR: awk not found"
    exit 1
fi

require_file "$RSSI_READER"
require_file "$LINK_FILTER"
require_file "$LINK_WATCH"
require_file "$LINK_GUARD"

if [[ "$ENABLE_LOG" == "true" ]]; then
    mkdir -p "$LOG_DIR"
fi

log "starting monitor pipeline"
log "iface=$IFACE interval=$INTERVAL threshold=$THRESHOLD degraded_count=$DEGRADED_COUNT recover_count=$RECOVER_COUNT"
log "monitor-only mode: detach_trigger.sh will not be executed"

produce_rssi() {
    while true; do
        if ! bash "$RSSI_READER" "$IFACE"; then
            log "warning: rssi_reader.sh failed for iface=$IFACE"
        fi

        sleep "$INTERVAL"
    done
}

run_pipeline() {
    produce_rssi \
        | python3 -u "$LINK_FILTER" \
        | python3 -u "$LINK_WATCH" --threshold "$THRESHOLD" \
        | python3 -u "$LINK_GUARD" \
            --degraded-count "$DEGRADED_COUNT" \
            --recover-count "$RECOVER_COUNT" \
            --sample-interval "$INTERVAL"
}

if [[ "$ENABLE_LOG" == "true" ]]; then
    log "logging final monitor output to $LOG_FILE"
    run_pipeline | tee -a "$LOG_FILE"
else
    run_pipeline
fi