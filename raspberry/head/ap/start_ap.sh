#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - AP start script
#
# Target:
#   Raspberry Pi 4
#   Debian GNU/Linux 13 trixie
#   wlan0 as AP-only interface
#
# DANGER:
#   This script switches wlan0 from Wi-Fi client mode to AP mode.
#   If the current SSH session is connected through wlan0, SSH may disconnect.
#
# Safety:
#   This script only runs when called with --yes.
#
# TODO:
#   Step 4 will add stop_ap.sh / recovery behavior.
#   Later, add a rollback timer so the Pi can automatically restore client
#   Wi-Fi mode if AP startup fails or the operator loses access.

IFACE="wlan0"
AP_ADDR="192.168.4.1/24"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOSTAPD_SRC="$SCRIPT_DIR/hostapd.conf"
DNSMASQ_SRC="$SCRIPT_DIR/dnsmasq.conf"

HOSTAPD_DST="/etc/hostapd/hostapd.conf"
DNSMASQ_DST="/etc/dnsmasq.d/hansel-ap.conf"

log() {
    echo "[start_ap] $*"
}

fail_hint() {
    echo
    echo "[start_ap] ERROR: AP startup failed."
    echo "[start_ap] Step 4 stop_ap.sh 또는 복구 스크립트 필요."
    echo "[start_ap] If SSH was connected through wlan0, the session may be lost."
    echo
}

trap fail_hint ERR

usage() {
    cat <<EOF
Usage:
  start_ap.sh --yes

This script will:
  - stop hostapd/dnsmasq
  - copy AP configuration files into /etc
  - disconnect wlan0 from Wi-Fi client mode
  - remove existing wlan0 IP addresses
  - assign 192.168.4.1/24 to wlan0
  - start dnsmasq
  - start hostapd

DANGER:
  Running this on a Pi currently accessed over wlan0 Wi-Fi can disconnect SSH.
EOF
}

if [[ "${1:-}" != "--yes" ]]; then
    usage
    echo
    echo "[start_ap] Refusing to continue. Pass --yes only when you intentionally want to switch wlan0 to AP mode."
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    echo "[start_ap] ERROR: this script must be run as root."
    echo "[start_ap] Re-run it with root privileges only when you are ready to risk losing wlan0 SSH."
    exit 1
fi

log "DANGER: wlan0 will be switched from Wi-Fi client mode to AP mode."
log "DANGER: if SSH is connected through wlan0, SSH may disconnect."
log "Interface: $IFACE"
log "AP address: $AP_ADDR"
echo

log "checking source configuration files"

if [[ ! -f "$HOSTAPD_SRC" ]]; then
    echo "[start_ap] ERROR: missing source file: $HOSTAPD_SRC"
    exit 1
fi

if [[ ! -f "$DNSMASQ_SRC" ]]; then
    echo "[start_ap] ERROR: missing source file: $DNSMASQ_SRC"
    exit 1
fi

log "stopping existing services"
systemctl stop hostapd || true
systemctl stop dnsmasq || true

log "installing configuration files"
install -d -m 755 /etc/hostapd
install -d -m 755 /etc/dnsmasq.d

install -m 600 "$HOSTAPD_SRC" "$HOSTAPD_DST"
install -m 644 "$DNSMASQ_SRC" "$DNSMASQ_DST"

log "unmasking hostapd service if needed"
systemctl unmask hostapd || true

log "unblocking Wi-Fi rfkill state"
rfkill unblock wifi

log "disconnecting wlan0 from NetworkManager client mode"
nmcli device disconnect "$IFACE" || true

log "marking wlan0 as unmanaged by NetworkManager"
nmcli device set "$IFACE" managed no

log "clearing existing wlan0 IP addresses"
ip addr flush dev "$IFACE"

log "bringing wlan0 up"
ip link set "$IFACE" up

log "assigning AP address to wlan0"
ip addr add "$AP_ADDR" dev "$IFACE"

log "starting dnsmasq"
systemctl start dnsmasq

log "starting hostapd"
systemctl start hostapd

log "AP startup sequence completed"
echo

log "status summary"
echo "----- ip addr show $IFACE -----"
ip addr show "$IFACE"

echo
echo "----- systemctl status dnsmasq --no-pager -----"
systemctl status dnsmasq --no-pager || true

echo
echo "----- systemctl status hostapd --no-pager -----"
systemctl status hostapd --no-pager || true

echo
log "Expected AP:"
log "  SSID: HANSEL_HEAD_AP"
log "  AP IP: 192.168.4.1/24"
log "  DHCP: 192.168.4.10 - 192.168.4.50"
log "  NAT: not configured in this step"