#!/usr/bin/env bash
set -e

# Node Pi raw H.264 Annex-B UDP video relay launcher.
# Forwards Head Pi video (UDP 5001) to the Android receiver (UDP 5001),
# byte-for-byte, with no RTP conversion and no H.264 parsing.
#
# Video port = 5001. command/control = 5000 and guard = 6000 are NOT handled here.

DST_IP="${1}"
LISTEN_PORT="${2:-5001}"
DST_PORT="${3:-5001}"

if [ -z "$DST_IP" ]; then
  echo "Usage: $0 <android-ip> [listen-port] [dst-port]"
  echo "Example: $0 192.168.4.10 5001 5001"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$SCRIPT_DIR/udp_h264_relay.py" \
  --dst-ip "$DST_IP" \
  --listen-port "$LISTEN_PORT" \
  --dst-port "$DST_PORT"
