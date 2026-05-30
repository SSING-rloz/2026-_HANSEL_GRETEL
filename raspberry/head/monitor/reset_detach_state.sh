#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - pre-mission detach latch reset
#
# WHY THIS EXISTS:
#   detach_bridge.py enforces a one-detach-per-node-per-mission LATCH. Once a
#   node has been physically detached, its station MAC is written into the
#   persistent state file and that node will NOT be detached again - not on
#   guard_status=recovered, and not after a service restart or Head reboot.
#
#   That latch is intentionally NEVER cleared at runtime. The ONLY supported
#   way to clear it is this script, run by a human BEFORE a new mission starts
#   (pre-mission init), while the nodes are physically re-attached.
#
# WHAT IT DOES:
#   Removes (or empties) /var/lib/hansel/detach_state.json so that the next
#   bridge start has an empty latch set and every node is eligible to detach
#   once again.
#
# WHEN TO RUN (operational procedure):
#   1. Mission ends; you physically re-attach all nodes to the train.
#   2. Run: sudo ./reset_detach_state.sh --yes
#   3. (Re)start the monitor service: sudo systemctl restart hansel-head-monitor
#   4. New mission begins with a clean latch.
#
# This is a pre-mission RESET, not a runtime re-arm. Do NOT wire this into any
# automatic flow.

STATE_FILE="${STATE_FILE:-/var/lib/hansel/detach_state.json}"

log() { echo "[reset_detach_state] $*"; }

if [[ "${1:-}" != "--yes" ]]; then
    cat <<EOF
Usage:
  sudo ./reset_detach_state.sh --yes [--state-file PATH]

Clears the persistent detach latch so every node may be detached again in the
NEXT mission. Run this ONLY before a new mission, after physically re-attaching
all nodes.

Current state file: $STATE_FILE
EOF
    exit 1
fi
shift

# Optional override: --state-file PATH
if [[ "${1:-}" == "--state-file" ]]; then
    STATE_FILE="${2:-}"
    if [[ -z "$STATE_FILE" ]]; then
        log "ERROR: --state-file requires a path"
        exit 1
    fi
fi

if [[ ! -e "$STATE_FILE" ]]; then
    log "no state file at $STATE_FILE - latch already clear, nothing to do."
    exit 0
fi

log "found existing latch state: $STATE_FILE"
log "contents before reset:"
cat "$STATE_FILE" || true

rm -f "$STATE_FILE"
log "removed $STATE_FILE - all nodes are eligible to detach again next mission."
log "Remember to (re)start the monitor service: systemctl restart hansel-head-monitor"
