#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - RSSI reader
#
# Target:
#   Raspberry Pi 4
#   Debian GNU/Linux 13 trixie
#   wlan0 in AP mode
#
# Purpose:
#   Read connected station/client RSSI values from:
#     iw dev <interface> station dump
#
# Note:
#   This script is meaningful after the Head Pi is running as an AP and
#   one or more clients are associated with the AP.
#
# Output format:
#   station=<mac> signal_dbm=<rssi>
#
# Example:
#   station=aa:bb:cc:dd:ee:ff signal_dbm=-52
#
# If no station is connected:
#   no_stations_connected interface=wlan0
#
# This script does NOT start AP mode.
# This script does NOT modify NetworkManager, hostapd, dnsmasq, or IP settings.

IFACE="${1:-wlan0}"

error() {
    echo "error=$1 interface=$IFACE" >&2
}

if ! command -v iw >/dev/null 2>&1; then
    error "iw_not_found"
    echo "hint=install_iw_or_check_path" >&2
    exit 1
fi

if [[ ! -d "/sys/class/net/$IFACE" ]]; then
    error "interface_not_found"
    echo "hint=check_interface_name_with_ip_link" >&2
    exit 1
fi

if ! DUMP="$(iw dev "$IFACE" station dump 2>&1)"; then
    error "station_dump_failed"
    printf '%s\n' "$DUMP" >&2
    exit 1
fi

if [[ -z "${DUMP//[[:space:]]/}" ]]; then
    echo "no_stations_connected interface=$IFACE"
    exit 0
fi

set +e
RESULT="$(
    printf '%s\n' "$DUMP" | awk '
        /^Station[[:space:]]+/ {
            mac=$2
        }

        /^[[:space:]]*signal:/ {
            if (mac != "") {
                signal=$2

                if (signal ~ /^-?[0-9]+$/) {
                    print "station=" mac " signal_dbm=" signal
                    count++
                }
            }
        }

        END {
            if (count == 0) {
                exit 2
            }
        }
    '
)"
AWK_STATUS=$?
set -e

if [[ "$AWK_STATUS" -eq 2 ]]; then
    echo "no_signal_values_found interface=$IFACE"
    echo "hint=station_dump_exists_but_signal_field_missing"
    exit 0
elif [[ "$AWK_STATUS" -ne 0 ]]; then
    error "awk_parse_failed"
    echo "awk_status=$AWK_STATUS" >&2
    exit 1
fi

printf '%s\n' "$RESULT"
