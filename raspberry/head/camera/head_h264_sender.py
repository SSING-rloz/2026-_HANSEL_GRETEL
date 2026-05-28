#!/usr/bin/env python3

import argparse
import signal
import socket
import time
from threading import Event

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput


class UdpChunkWriter:
    def __init__(self, dst_ip: str, dst_port: int, mtu: int = 1200):
        self.dst = (dst_ip, dst_port)
        self.mtu = mtu
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect(self.dst)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_000_000)

        self.bytes_sent = 0
        self.packets_sent = 0

    def write(self, data: bytes) -> int:
        if not data:
            return 0

        view = memoryview(data)
        total = len(view)

        for offset in range(0, total, self.mtu):
            chunk = view[offset:offset + self.mtu]
            self.sock.send(chunk)
            self.packets_sent += 1

        self.bytes_sent += total
        return total

    def flush(self):
        pass

    def close(self):
        self.sock.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Head Pi CSI camera H.264 UDP sender"
    )

    parser.add_argument("--dst", required=True, help="receiver IP address")
    parser.add_argument("--port", type=int, default=5000, help="receiver UDP port")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate", type=int, default=1_000_000)
    parser.add_argument("--mtu", type=int, default=1200)
    parser.add_argument("--duration", type=int, default=0)

    return parser.parse_args()


def main():
    args = parse_args()
    stop_event = Event()

    def handle_stop(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    print("[head-camera] starting")
    print(f"[head-camera] dst={args.dst}:{args.port}")
    print(f"[head-camera] size={args.width}x{args.height}, fps={args.fps}")
    print(f"[head-camera] bitrate={args.bitrate}")

    writer = UdpChunkWriter(args.dst, args.port, args.mtu)

    picam2 = Picamera2()

    video_config = picam2.create_video_configuration(
        main={
            "size": (args.width, args.height),
            "format": "YUV420",
        },
        controls={
            "FrameRate": args.fps,
        },
        buffer_count=6,
    )

    picam2.configure(video_config)

    encoder = H264Encoder(
        bitrate=args.bitrate,
        repeat=True,
    )

    output = FileOutput(writer)

    start_time = time.monotonic()

    try:
        picam2.start_recording(encoder, output)
        print("[head-camera] streaming started")

        while not stop_event.is_set():
            time.sleep(1)

            elapsed = time.monotonic() - start_time
            avg_mbps = (writer.bytes_sent * 8) / elapsed / 1_000_000

            print(
                f"[head-camera] elapsed={elapsed:.1f}s "
                f"sent={writer.bytes_sent}B "
                f"packets={writer.packets_sent} "
                f"avg={avg_mbps:.2f}Mbps"
            )

            if args.duration > 0 and elapsed >= args.duration:
                break

    finally:
        print("[head-camera] stopping")

        try:
            picam2.stop_recording()
        except Exception as e:
            print(f"[head-camera] stop_recording warning: {e}")

        writer.close()
        print("[head-camera] stopped")


if __name__ == "__main__":
    main()