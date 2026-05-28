#!/usr/bin/env bash
set -e

DST_IP="${1}"
DST_PORT="${2:-5000}"

if [ -z "$DST_IP" ]; then
  echo "Usage: $0 <receiver-ip> [receiver-port]"
  echo "Example: $0 192.168.50.23 5000"
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