#!/usr/bin/env bash
set -e

# Sends raw H.264 Annex-B over UDP (NOT RTP) to the Android receiver.
# Default video port is 5001 (command/control = 5000, guard = 6000).

DST_IP="${1}"
DST_PORT="${2:-5001}"

if [ -z "$DST_IP" ]; then
  echo "Usage: $0 <receiver-ip> [receiver-port]"
  echo "Example: $0 192.168.4.10 5001"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$SCRIPT_DIR/head_h264_sender.py" \
  --dst "$DST_IP" \
  --port "$DST_PORT" \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --bitrate 1000000