#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Node2 Pi - HANSEL_HEAD_AP static-IP join script
#
# Purpose:
#   Create/update a NetworkManager Wi-Fi profile so this Node2 Pi connects to
#   the Head Pi AP (HANSEL_HEAD_AP) with the FIXED address 192.168.4.12/24.
#
# Deployment address policy (MVP):
#   Head Pi AP   : 192.168.4.1   (gateway / DNS)
#   Node1 Pi     : 192.168.4.11
#   Node2 Pi     : 192.168.4.12  <-- THIS node
#   Node3 Pi     : 192.168.4.13
#   Android phone: 192.168.4.20  (set manually on the phone)
#
# DANGER:
#   Applying this profile changes how wlan0 connects. If you are currently
#   reaching this Pi over a DIFFERENT Wi-Fi network through wlan0, that SSH
#   session may drop when it switches to HANSEL_HEAD_AP. Have console/keyboard
#   recovery available on first apply.
#
# Safety:
#   Runs only when called with --yes.

IFACE="wlan0"
SSID="HANSEL_HEAD_AP"
WIFI_PSK="12345678"

CON_NAME="hansel-ap"
STATIC_IP="192.168.4.12/24"
GATEWAY="192.168.4.1"
DNS="192.168.4.1"

log() { echo "[setup_static_ip:node2] $*"; }

usage() {
    cat <<EOF
Usage:
  setup_static_ip.sh --yes

This script will (via NetworkManager / nmcli):
  - create or update Wi-Fi connection "$CON_NAME"
  - SSID=$SSID, WPA2-PSK
  - ipv4.method manual, address $STATIC_IP, gateway $GATEWAY, dns $DNS
  - autoconnect yes
  - bring the connection up on $IFACE

DANGER:
  This changes wlan0 connectivity and may drop a current SSH session.
EOF
}

if [[ "${1:-}" != "--yes" ]]; then
    usage
    echo
    log "Refusing to continue without --yes."
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    log "ERROR: must be run as root (nmcli profile changes)."
    exit 1
fi

if ! command -v nmcli >/dev/null 2>&1; then
    log "ERROR: nmcli not found. NetworkManager is required."
    exit 1
fi

log "DANGER: wlan0 will be (re)connected to $SSID with static $STATIC_IP."
log "If this SSH session runs over a different wlan0 network, it may drop."

if nmcli -t -f NAME connection show | grep -Fxq "$CON_NAME"; then
    log "updating existing connection profile: $CON_NAME"
else
    log "creating connection profile: $CON_NAME"
    nmcli connection add type wifi con-name "$CON_NAME" ifname "$IFACE" ssid "$SSID"
fi

nmcli connection modify "$CON_NAME" \
    connection.interface-name "$IFACE" \
    802-11-wireless.ssid "$SSID" \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$WIFI_PSK" \
    ipv4.method manual \
    ipv4.addresses "$STATIC_IP" \
    ipv4.gateway "$GATEWAY" \
    ipv4.dns "$DNS" \
    ipv6.method ignore \
    connection.autoconnect yes \
    connection.autoconnect-priority 100

log "bringing connection up"
nmcli connection up "$CON_NAME" ifname "$IFACE"

log "done. Current wlan0 addresses:"
ip addr show "$IFACE" | grep -w inet || true
