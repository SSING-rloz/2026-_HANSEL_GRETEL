#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - AP stop / recovery script
#
# Target:
#   Raspberry Pi 4
#   Debian GNU/Linux 13 trixie
#   wlan0 recovery from AP-only mode back to Wi-Fi client mode
#
# Pair script:
#   This script is the recovery counterpart of start_ap.sh.
#
# Purpose:
#   - stop hostapd
#   - stop dnsmasq
#   - remove AP IP from wlan0
#   - return wlan0 to NetworkManager management
#   - reconnect to the previous Wi-Fi client connection
#
# Note:
#   If SSH was already disconnected after entering AP mode, this script can be
#   run from a direct console/keyboard/monitor, or from an SSH session reached
#   through the temporary AP network.
#
# Safety:
#   This script only runs when called with --yes.

IFACE="wlan0"
OLD_CONN="netplan-wlan0-ssing"

log() {
    echo "[stop_ap] $*"
}

warn() {
    echo "[stop_ap] WARNING: $*"
}

fail_hint() {
    echo
    echo "[stop_ap] ERROR: recovery script failed before completion."
    echo "[stop_ap] Manual recovery may be required."
    echo "[stop_ap] Useful manual checks:"
    echo "[stop_ap]   nmcli device status"
    echo "[stop_ap]   nmcli connection show"
    echo "[stop_ap]   ip addr show $IFACE"
    echo "[stop_ap]   systemctl status NetworkManager --no-pager"
    echo
}

trap fail_hint ERR

usage() {
    cat <<EOF
Usage:
  stop_ap.sh --yes

This script will:
  - stop hostapd
  - stop dnsmasq
  - flush IP addresses from wlan0
  - bring wlan0 up
  - enable Wi-Fi radio
  - return wlan0 to NetworkManager managed mode
  - restart NetworkManager
  - try to reconnect to: $OLD_CONN

This is intended to reverse the effect of start_ap.sh.
EOF
}

if [[ "${1:-}" != "--yes" ]]; then
    usage
    echo
    echo "[stop_ap] Refusing to continue. Pass --yes only when you intentionally want to stop AP mode."
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "[stop_ap] ERROR: this script must be run as root."
    echo "[stop_ap] Re-run it with root privileges only when you are ready to recover wlan0 client mode."
    exit 1
fi

log "stopping AP services"
systemctl stop hostapd || true
systemctl stop dnsmasq || true

log "flushing IP addresses from $IFACE"
ip addr flush dev "$IFACE" || true

log "bringing $IFACE up"
ip link set "$IFACE" up

log "enabling Wi-Fi radio"
nmcli radio wifi on || warn "failed to enable Wi-Fi radio through nmcli"

log "returning $IFACE to NetworkManager managed mode"
nmcli device set "$IFACE" managed yes || warn "failed to set $IFACE managed yes before NetworkManager restart"

log "restarting NetworkManager"
systemctl restart NetworkManager

log "waiting for NetworkManager to settle"
sleep 3

log "ensuring $IFACE is managed after NetworkManager restart"
nmcli device set "$IFACE" managed yes || warn "failed to set $IFACE managed yes after NetworkManager restart"

log "trying to reconnect to previous Wi-Fi connection: $OLD_CONN"
if nmcli connection up "$OLD_CONN" ifname "$IFACE"; then
    log "reconnected to $OLD_CONN"
else
    warn "automatic reconnect failed"
    warn "manual recovery may be required"
    warn "check available connections with:"
    warn "  nmcli connection show"
    warn "check Wi-Fi device status with:"
    warn "  nmcli device status"
    warn "try reconnecting manually to the correct Wi-Fi connection"
fi

echo
log "recovery status summary"

echo "----- hostname -I -----"
hostname -I || true

echo
echo "----- nmcli device status -----"
nmcli device status || true

echo
echo "----- ip addr show $IFACE -----"
ip addr show "$IFACE" || true

echo
echo "----- systemctl status NetworkManager --no-pager -----"
systemctl status NetworkManager --no-pager || true

echo
log "stop_ap.sh completed"
log "If $IFACE received a 10.x/192.168.x client IP again, Wi-Fi client recovery likely worked."