#!/usr/bin/env python3

# Node Pi raw H.264 Annex-B over UDP relay.
#
# This relay forwards UDP datagrams unchanged. It does NOT parse H.264,
# does NOT reassemble NAL units, and does NOT convert to/from RTP. Each datagram
# payload is forwarded byte-for-byte. The Android receiver is responsible for
# byte-stream accumulation and Annex-B start-code NAL recovery.
#
# Video path:
#   Head Pi sender -> (this) Node Pi relay -> Android receiver
#
# Ports (video port is intentionally different from the control port):
#   video   UDP = 5001  (this relay: listen 5001, forward to Android 5001)
#   command UDP = 5000  (motor/servo control - handled elsewhere, NOT here)
#   guard   UDP = 6000  (auto-detach signalling - handled elsewhere, NOT here)
#
# Standard library only (Python 3).

import argparse
import signal
import socket
import time


def parse_args():
    parser = argparse.ArgumentParser(
        description="Node Pi raw H.264 Annex-B UDP relay (Head Pi -> Android)"
    )

    parser.add_argument("--listen-ip", default="0.0.0.0", help="local bind IP")
    parser.add_argument("--listen-port", type=int, default=5001, help="local video UDP listen port")
    parser.add_argument("--dst-ip", required=True, help="Android receiver IP")
    parser.add_argument("--dst-port", type=int, default=5001, help="Android receiver UDP port")
    parser.add_argument("--packet-size", type=int, default=65535, help="max datagram recv size")
    parser.add_argument("--stats-interval", type=float, default=1.0, help="stats print interval (s)")

    return parser.parse_args()


def main():
    args = parse_args()

    stop = False

    def handle_stop(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    listen_addr = (args.listen_ip, args.listen_port)
    dst_addr = (args.dst_ip, args.dst_port)

    print("[node-relay] raw H.264 Annex-B over UDP relay (no RTP, no parsing)")
    print(f"[node-relay] listen  {listen_addr[0]}:{listen_addr[1]}")
    print(f"[node-relay] forward {dst_addr[0]}:{dst_addr[1]}")

    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    packets = 0
    bytes_total = 0
    last_stats = time.monotonic()

    try:
        recv_sock.bind(listen_addr)
        recv_sock.settimeout(args.stats_interval)
        print(f"[node-relay] ready on {listen_addr[0]}:{listen_addr[1]}")

        while not stop:
            try:
                data, _src = recv_sock.recvfrom(args.packet_size)
            except socket.timeout:
                data = None

            if data:
                # Forward the datagram payload byte-for-byte. Do not modify.
                send_sock.sendto(data, dst_addr)
                packets += 1
                bytes_total += len(data)

            now = time.monotonic()
            if now - last_stats >= args.stats_interval:
                print(
                    f"[node-relay] packets={packets} bytes={bytes_total} "
                    f"-> {dst_addr[0]}:{dst_addr[1]}"
                )
                last_stats = now

    except OSError as e:
        print(f"[node-relay] socket error: {e}")
        print(f"Try: sudo pkill -f udp_h264_relay.py")
    except Exception as e:
        print(f"[node-relay] error: {e}")
    finally:
        recv_sock.close()
        send_sock.close()
        print("[node-relay] stopped")


if __name__ == "__main__":
    main()
