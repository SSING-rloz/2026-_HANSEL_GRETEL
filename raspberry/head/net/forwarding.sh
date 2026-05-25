#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - forwarding / NAT helper
#
# Target:
#   Raspberry Pi 4
#   Debian GNU/Linux 13 trixie
#   AP interface: wlan0
#   AP subnet: 192.168.4.0/24
#
# Purpose:
#   Prepare optional IPv4 forwarding and NAT masquerade for future
#   Pi-Pi relay, routing, or upstream network experiments.
#
# Important:
#   Local AP-only communication does NOT require NAT.
#   NAT is only needed when AP clients must reach another network
#   through an upstream interface such as eth0 or usb0.
#
# Scope:
#   - Uses nftables.
#   - Manages only table ip hansel_nat.
#   - Does NOT flush the global nftables ruleset.
#   - Does NOT touch table inet hansel_fw from firewall.sh.
#   - Does NOT start/stop AP mode.
#   - Does NOT modify NetworkManager, hostapd, dnsmasq, or wlan0 IP settings.

AP_IFACE="wlan0"
AP_SUBNET="192.168.4.0/24"
UPSTREAM_IFACE=""

ACTION=""
APPLY="false"
PRINT_ONLY="false"
DISABLE_FORWARDING="false"

usage() {
    cat <<EOF
Usage:
  forwarding.sh --yes --enable --upstream-iface <iface> [options]
  forwarding.sh --yes --disable [--disable-forwarding]
  forwarding.sh --print --enable --upstream-iface <iface> [options]
  forwarding.sh --print --disable [--disable-forwarding]

Actions:
  --enable                  Enable IPv4 forwarding and create NAT masquerade table
  --disable                 Remove table ip hansel_nat

Required for --enable:
  --upstream-iface <iface>  Upstream interface, e.g. eth0, usb0

Options:
  --ap-iface <iface>        AP interface. Default: wlan0
  --ap-subnet <cidr>        AP subnet. Default: 192.168.4.0/24
  --disable-forwarding      With --disable, also set net.ipv4.ip_forward=0
  --yes                     Actually apply changes
  --print, --dry-run        Print planned commands/rules only
  -h, --help                Show this help

Notes:
  - NAT/forwarding is not needed for AP-local communication.
  - eth0 was previously NO-CARRIER, so do not assume upstream works yet.
  - This script manages only table ip hansel_nat.
  - It does not touch firewall.sh table inet hansel_fw.
EOF
}

log() {
    echo "[forwarding] $*" >&2
}

is_iface_name() {
    local value="$1"
    [[ "$value" =~ ^[A-Za-z0-9_.:-]+$ ]]
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable)
            ACTION="enable"
            shift
            ;;

        --disable)
            ACTION="disable"
            shift
            ;;

        --ap-iface)
            AP_IFACE="${2:-}"
            if [[ -z "$AP_IFACE" ]] || ! is_iface_name "$AP_IFACE"; then
                log "ERROR: --ap-iface requires a valid interface name"
                exit 1
            fi
            shift 2
            ;;

        --upstream-iface)
            UPSTREAM_IFACE="${2:-}"
            if [[ -z "$UPSTREAM_IFACE" ]] || ! is_iface_name "$UPSTREAM_IFACE"; then
                log "ERROR: --upstream-iface requires a valid interface name"
                exit 1
            fi
            shift 2
            ;;

        --ap-subnet)
            AP_SUBNET="${2:-}"
            if [[ -z "$AP_SUBNET" ]]; then
                log "ERROR: --ap-subnet requires a value"
                exit 1
            fi
            shift 2
            ;;

        --disable-forwarding)
            DISABLE_FORWARDING="true"
            shift
            ;;

        --yes)
            APPLY="true"
            shift
            ;;

        --print|--dry-run)
            PRINT_ONLY="true"
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

if [[ -z "$ACTION" ]]; then
    usage
    echo
    log "ERROR: choose exactly one action: --enable or --disable"
    exit 1
fi

if [[ "$ACTION" == "enable" && -z "$UPSTREAM_IFACE" ]]; then
    usage
    echo
    log "ERROR: --enable requires --upstream-iface <iface>"
    exit 1
fi

if [[ "$ACTION" == "disable" && -n "$UPSTREAM_IFACE" ]]; then
    log "WARNING: --upstream-iface is ignored with --disable"
fi

generate_nat_ruleset() {
    cat <<EOF
table ip hansel_nat {
    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;

        # Masquerade only AP subnet traffic leaving through upstream interface.
        ip saddr $AP_SUBNET oifname "$UPSTREAM_IFACE" masquerade
    }
}
EOF
}

print_enable_plan() {
    cat <<EOF
# Planned enable actions:
sysctl -w net.ipv4.ip_forward=1

# Replace only table ip hansel_nat:
nft delete table ip hansel_nat 2>/dev/null || true
nft -f - <<'NFT'
$(generate_nat_ruleset)
NFT
EOF
}

print_disable_plan() {
    cat <<EOF
# Planned disable actions:
nft delete table ip hansel_nat 2>/dev/null || true
EOF

    if [[ "$DISABLE_FORWARDING" == "true" ]]; then
        cat <<EOF
sysctl -w net.ipv4.ip_forward=0
EOF
    else
        cat <<EOF
# net.ipv4.ip_forward is left unchanged.
# Use --disable-forwarding to set it to 0.
EOF
    fi
}

if [[ "$PRINT_ONLY" == "true" ]]; then
    if [[ "$ACTION" == "enable" ]]; then
        print_enable_plan
    else
        print_disable_plan
    fi
    exit 0
fi

if [[ "$APPLY" != "true" ]]; then
    usage
    echo
    log "Refusing to apply forwarding/NAT changes without --yes."
    log "Use --print first to inspect planned changes."
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    log "ERROR: this script must be run as root to apply forwarding/NAT changes."
    exit 1
fi

if ! command -v nft >/dev/null 2>&1; then
    log "ERROR: nft command not found. Install nftables before applying this script."
    exit 1
fi

if ! command -v sysctl >/dev/null 2>&1; then
    log "ERROR: sysctl command not found."
    exit 1
fi

if [[ "$ACTION" == "enable" ]]; then
    log "WARNING: enabling IPv4 forwarding and NAT."
    log "AP interface: $AP_IFACE"
    log "AP subnet: $AP_SUBNET"
    log "Upstream interface: $UPSTREAM_IFACE"
    log "This may change network routing behavior on the Pi."
    log "This script will manage only table ip hansel_nat."

    sysctl -w net.ipv4.ip_forward=1

    if nft list table ip hansel_nat >/dev/null 2>&1; then
        log "deleting existing table ip hansel_nat"
        nft delete table ip hansel_nat
    fi

    log "creating table ip hansel_nat"
    generate_nat_ruleset | nft -f -

    log "applied NAT table ip hansel_nat"
    nft list table ip hansel_nat
    exit 0
fi

if [[ "$ACTION" == "disable" ]]; then
    log "WARNING: disabling/removing NAT table created by this script."
    log "This will delete only table ip hansel_nat."
    log "It will not touch table inet hansel_fw."

    if nft list table ip hansel_nat >/dev/null 2>&1; then
        nft delete table ip hansel_nat
        log "deleted table ip hansel_nat"
    else
        log "table ip hansel_nat does not exist; nothing to delete"
    fi

    if [[ "$DISABLE_FORWARDING" == "true" ]]; then
        log "WARNING: setting net.ipv4.ip_forward=0."
        log "If another service needs forwarding, this may break it."
        sysctl -w net.ipv4.ip_forward=0
    else
        log "leaving net.ipv4.ip_forward unchanged"
        log "use --disable-forwarding if you intentionally want to set it to 0"
    fi

    exit 0
fi