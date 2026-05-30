#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - systemd install/enable script
#
# Installs the Head systemd units into /etc/systemd/system, resolving the
# repo path, runs daemon-reload, and ENABLES them for boot.
#
# DELIBERATELY SAFE:
#   - This script does NOT start the AP and does NOT switch wlan0 to AP mode.
#   - It enables units (boot autostart) but only START them when you choose.
#   - hansel-ap.service is the dangerous one: enabling means it WILL start on
#     the NEXT boot. If you are connected over wlan0, plan console recovery
#     (stop_ap.sh) before rebooting.
#
# Units installed:
#   hansel-ap.service             (AP; oneshot)
#   hansel-head-control.service   (UDP 5000 control)
#   hansel-head-monitor.service   (RSSI monitor + auto-detach bridge)
#   hansel-head-camera.service    (H.264 UDP sender)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HEAD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEST="/etc/systemd/system"

UNITS=(
    hansel-ap.service
    hansel-head-control.service
    hansel-head-monitor.service
    hansel-head-camera.service
)

log() { echo "[install_head] $*"; }

if [[ "${1:-}" != "--yes" ]]; then
    cat <<EOF
Usage:
  sudo ./install_head_services.sh --yes

Installs + enables Head systemd units (does NOT start AP / does NOT switch wlan0).
HEAD_DIR resolved to: $HEAD_DIR
EOF
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    log "ERROR: must run as root."
    exit 1
fi

for unit in "${UNITS[@]}"; do
    src="$SCRIPT_DIR/$unit"
    if [[ ! -f "$src" ]]; then
        log "ERROR: missing unit template: $src"
        exit 1
    fi
    log "installing $unit (HEAD_DIR=$HEAD_DIR)"
    sed "s|__HEAD_DIR__|$HEAD_DIR|g" "$src" > "$DEST/$unit"
    chmod 644 "$DEST/$unit"
done

log "daemon-reload"
systemctl daemon-reload

for unit in "${UNITS[@]}"; do
    log "enabling $unit"
    systemctl enable "$unit"
done

cat <<EOF

[install_head] Done. Units are ENABLED for boot but NOT started now.

Start order (manual, when ready):
  1) sudo systemctl start hansel-ap.service        # DANGER: wlan0 -> AP, SSH may drop
  2) sudo systemctl start hansel-head-control.service
  3) sudo systemctl start hansel-head-monitor.service
  4) sudo systemctl start hansel-head-camera.service

Recovery (restore wlan0 client mode):
  sudo bash $HEAD_DIR/ap/stop_ap.sh --yes
  # or: sudo systemctl stop hansel-ap.service

Pre-mission detach reset (run BEFORE each new mission, after physically
re-attaching all nodes; the detach latch is one-per-node-per-mission and is
NEVER cleared at runtime):
  sudo bash $HEAD_DIR/monitor/reset_detach_state.sh --yes
  sudo systemctl restart hansel-head-monitor.service

Check:
  systemctl status hansel-head-control.service
  journalctl -u hansel-head-camera.service -f
EOF
