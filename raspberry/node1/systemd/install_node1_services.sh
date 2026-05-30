#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Node1 Pi - systemd install/enable script
#
# Installs Node1 systemd units into /etc/systemd/system, resolving the repo
# path, runs daemon-reload, and ENABLES them for boot.
#
# DELIBERATELY SAFE:
#   - This does NOT change wlan0 networking. Run net/setup_static_ip.sh --yes
#     separately to join HANSEL_HEAD_AP with static 192.168.4.11.
#   - Enabling means the units start on the NEXT boot. They are not started now
#     unless you start them explicitly.
#
# Units installed:
#   hansel-node1-control.service  (UDP 5000 control)
#   hansel-node1-relay.service    (video relay 5001 -> Node2)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DEST="/etc/systemd/system"

UNITS=(
    hansel-node1-control.service
    hansel-node1-relay.service
)

log() { echo "[install_node1] $*"; }

if [[ "${1:-}" != "--yes" ]]; then
    cat <<EOF
Usage:
  sudo ./install_node1_services.sh --yes

Installs + enables Node1 systemd units (does NOT touch wlan0 networking).
NODE_DIR resolved to: $NODE_DIR
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
    log "installing $unit (NODE_DIR=$NODE_DIR)"
    sed "s|__NODE_DIR__|$NODE_DIR|g" "$src" > "$DEST/$unit"
    chmod 644 "$DEST/$unit"
done

log "daemon-reload"
systemctl daemon-reload

for unit in "${UNITS[@]}"; do
    log "enabling $unit"
    systemctl enable "$unit"
done

cat <<EOF

[install_node1] Done. Units ENABLED for boot but NOT started now.

Static IP (run once, separately):
  sudo bash $NODE_DIR/net/setup_static_ip.sh --yes   # wlan0 -> HANSEL_HEAD_AP, 192.168.4.11

Start now (optional):
  sudo systemctl start hansel-node1-control.service
  sudo systemctl start hansel-node1-relay.service

Check:
  systemctl status hansel-node1-control.service
  journalctl -u hansel-node1-relay.service -f
EOF
