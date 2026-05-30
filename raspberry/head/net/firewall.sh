#!/bin/bash
set -euo pipefail

# HANSEL/GRETEL Head Pi - AP local firewall
#
# Target:
#   Raspberry Pi 4
#   Debian GNU/Linux 13 trixie
#   AP interface: wlan0
#   AP subnet: 192.168.4.0/24
#
# Purpose:
#   Define a minimal nftables firewall table for the Head Pi AP local network.
#
# Scope:
#   - Allows AP clients to reach selected Head Pi services.
#   - Does NOT configure NAT.
#   - Does NOT configure IP forwarding.
#   - Does NOT start or stop AP mode.
#   - Does NOT touch NetworkManager, hostapd, dnsmasq, or interface addresses.
#
# Safety:
#   This script only manages table inet hansel_fw.
#   It does NOT flush the whole nftables ruleset.
#   Default input policy is accept during prototype/testing to avoid lockout.

AP_IFACE="wlan0"
AP_SUBNET="192.168.4.0/24"

SSH_PORT="22"
CONTROL_PORT="5000"

APPLY="false"
PRINT_ONLY="false"

usage() {
    cat <<EOF
Usage:
  firewall.sh --yes [options]
  firewall.sh --print [options]
  firewall.sh --dry-run [options]

Required for applying:
  --yes                  Actually apply nftables table inet hansel_fw

Print-only:
  --print                Print generated nft rules and exit
  --dry-run              Same as --print

Options:
  --iface <name>         AP interface. Default: wlan0
  --ap-subnet <cidr>     AP subnet. Default: 192.168.4.0/24
  --ssh-port <port>      SSH TCP port. Default: 22
  --control-port <port>  Control UDP port. Default: 5000
  -h, --help             Show this help

Allowed AP-local services (Head Pi INPUT, i.e. traffic the Head Pi receives):
  - TCP 22    SSH
  - UDP 67/68 DHCP (Head Pi runs dnsmasq for AP clients)
  - UDP/TCP 53 DNS (Head Pi runs dnsmasq for AP clients)
  - UDP 5000  control command (Head_control.py listens on 0.0.0.0:5000)

Intentionally NOT opened here (Head Pi does not receive these):
  - UDP 5001  video stream: the Head Pi is the camera SENDER, not a receiver.
              Received by the Node relay / Android, not by the Head Pi.
  - UDP 6000  guard / auto-detach: received where keyboard.py runs
              (Controller PC), not by the Head Pi. Add a Head INPUT rule
              only if the receiver is ever confirmed to run on the Head Pi.
  - UDP 5005  rssi_listen: Node1's receive port, not a Head Pi service.

Notes:
  - This is the Head Pi INPUT firewall. It only allows services the Head Pi
    actually receives. It is NOT a place to express the whole system port map;
    the full port table belongs in project documentation.
  - NAT/forwarding is intentionally not configured here.
  - routing/NAT should be handled later by net/forwarding.sh.
  - This script does not flush the global nftables ruleset.
EOF
}

log() {
    echo "[firewall] $*" >&2
}

is_port() {
    local value="$1"

    [[ "$value" =~ ^[0-9]+$ ]] && [[ "$value" -ge 1 ]] && [[ "$value" -le 65535 ]]
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)
            APPLY="true"
            shift
            ;;

        --print|--dry-run)
            PRINT_ONLY="true"
            shift
            ;;

        --iface)
            AP_IFACE="${2:-}"
            if [[ -z "$AP_IFACE" ]]; then
                log "ERROR: --iface requires a value"
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

        --ssh-port)
            SSH_PORT="${2:-}"
            if ! is_port "$SSH_PORT"; then
                log "ERROR: --ssh-port must be 1..65535"
                exit 1
            fi
            shift 2
            ;;

        --control-port)
            CONTROL_PORT="${2:-}"
            if ! is_port "$CONTROL_PORT"; then
                log "ERROR: --control-port must be 1..65535"
                exit 1
            fi
            shift 2
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

RULESET="$(cat <<EOF
table inet hansel_fw {
    chain input {
        type filter hook input priority 0; policy accept;

        # Keep local loopback and existing connections working.
        iifname "lo" accept
        ct state established,related accept

        # DHCP from AP clients to Head Pi.
        iifname "$AP_IFACE" ip saddr $AP_SUBNET udp dport { 67, 68 } accept

        # DNS from AP clients to Head Pi.
        iifname "$AP_IFACE" ip saddr $AP_SUBNET udp dport 53 accept
        iifname "$AP_IFACE" ip saddr $AP_SUBNET tcp dport 53 accept

        # SSH from AP clients to Head Pi.
        iifname "$AP_IFACE" ip saddr $AP_SUBNET tcp dport $SSH_PORT accept

        # Control command server (UDP 5000): keyboard.py -> Head_control.py.
        # Head_control.py binds 0.0.0.0:5000 (SOCK_DGRAM), so the Head Pi
        # genuinely receives this. (Previously a stale tcp dport rule.)
        iifname "$AP_IFACE" ip saddr $AP_SUBNET udp dport $CONTROL_PORT accept

        # Intentionally NOT opened here (Head Pi does not receive these):
        #   UDP 5001 video : Head Pi is the camera SENDER; received by the
        #                    Node relay / Android, not by the Head Pi.
        #   UDP 6000 guard : auto-detach receiver lives where keyboard.py runs
        #                    (Controller PC), not on the Head Pi.
        #   UDP 5005 rssi_listen : Node1's receive port, not a Head service.
        # Add Head INPUT rules for these only if a receiver is ever confirmed
        # to run on the Head Pi itself.

        # Prototype/testing mode:
        # policy accept is intentionally kept to avoid SSH/AP lockout.
        # Later, after recovery path is proven, this can be changed to policy drop
        # with explicit allow rules only.
    }
}
EOF
)"

if [[ "$PRINT_ONLY" == "true" ]]; then
    echo "$RULESET"
    exit 0
fi

if [[ "$APPLY" != "true" ]]; then
    usage
    echo
    log "Refusing to apply firewall without --yes."
    log "Use --print first to inspect the generated nft rules."
    exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
    log "ERROR: this script must be run as root to apply nftables rules."
    exit 1
fi

if ! command -v nft >/dev/null 2>&1; then
    log "ERROR: nft command not found. Install nftables before applying this script."
    exit 1
fi

log "WARNING: applying nftables table inet hansel_fw."
log "This script will delete and recreate only table inet hansel_fw."
log "It will NOT flush the global nftables ruleset."
log "NAT/forwarding is NOT configured here."

if nft list table inet hansel_fw >/dev/null 2>&1; then
    log "deleting existing table inet hansel_fw"
    nft delete table inet hansel_fw
fi

log "creating table inet hansel_fw"
printf '%s\n' "$RULESET" | nft -f -

log "applied firewall table inet hansel_fw"
log "current hansel_fw rules:"
nft list table inet hansel_fw