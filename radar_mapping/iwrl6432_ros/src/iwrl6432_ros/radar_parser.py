#!/usr/bin/env python3
"""Offline parser for xWRL6432 Motion/Presence demo UART packets.

Official local SDK evidence (all offsets are little-endian, as documented in
reference/MOTION_AND_PRESENCE_DETECTION_DEMO.html:1278-1302):

* MmwDemo_output_message_header: reference/motion_detect.h:1350-1378 (40 B)
* MmwDemo_output_message_tl: reference/motion_detect.h:326-334 (8 B)
* MmwDemo_output_message_point_unit: reference/motion_detect.h:343-360 (20 B)
* MmwDemo_output_message_UARTpoint: reference/motion_detect.h:369-383 (10 B)
* MMWDEMO_OUTPUT_EXT_MSG_DETECTED_POINTS: enum starts at 300 and compressed
  point type is 301, reference/motion_detect.h:1270-1276 and
  reference/motion_detect.c:886-891.
* Magic word values: reference/motion_detect.c:844-847.
* totalPacketLen is padded to 32 B: reference/motion_detect.h:77 and
  reference/motion_detect.c:1058-1061,1390-1393.
"""

import argparse
import csv
import json
import math
from pathlib import Path
import struct
import sys


MAGIC = bytes.fromhex("02 01 04 03 06 05 08 07")
HEADER = struct.Struct("<4H8I")
TLV_HEADER = struct.Struct("<II")
POINT_UNIT = struct.Struct("<4f2H")
POINT = struct.Struct("<4h2B")
HEADER_SIZE = 40
TLV_TYPE_COMPRESSED_POINTS = 301
PACKET_ALIGNMENT = 32
MAX_PACKET_SIZE = 16 * 1024 * 1024


class PacketError(ValueError):
    pass


def parse_compressed_points(payload, header_point_count):
    if len(payload) < POINT_UNIT.size:
        raise PacketError("compressed point TLV is shorter than 20-byte unit structure")
    xyz_unit, doppler_unit, snr_unit, noise_unit, major_count, minor_count = (
        POINT_UNIT.unpack_from(payload)
    )
    point_bytes = len(payload) - POINT_UNIT.size
    if point_bytes % POINT.size:
        raise PacketError("compressed point payload is not a multiple of 10 bytes")
    payload_count = point_bytes // POINT.size
    unit_count = major_count + minor_count
    if unit_count != payload_count:
        raise PacketError(
            f"unit point count {unit_count} != payload point count {payload_count}"
        )
    if header_point_count != payload_count:
        raise PacketError(
            f"header numDetectedObj {header_point_count} != payload count {payload_count}"
        )
    if not all(math.isfinite(v) and v >= 0 for v in
               (xyz_unit, doppler_unit, snr_unit, noise_unit)):
        raise PacketError("invalid point unit value")

    points = []
    offset = POINT_UNIT.size
    for index in range(payload_count):
        x_raw, y_raw, z_raw, doppler_raw, snr_raw, noise_raw = POINT.unpack_from(
            payload, offset
        )
        offset += POINT.size
        points.append({
            "point_index": index,
            # Official structures store signed int16 coordinate/velocity counts
            # and uint8 SNR/noise counts; physical value = count * matching unit.
            "x": x_raw * xyz_unit,
            "y": y_raw * xyz_unit,
            "z": z_raw * xyz_unit,
            "doppler": doppler_raw * doppler_unit,
            "snr": snr_raw * snr_unit,
            "noise": noise_raw * noise_unit,
            "motion_mode": "major" if index < major_count else "minor",
        })
    return points, {
        "xyz_unit": xyz_unit,
        "doppler_unit": doppler_unit,
        "snr_unit": snr_unit,
        "noise_unit": noise_unit,
        "major_point_count": major_count,
        "minor_point_count": minor_count,
    }


def parse_packet(packet, stream_offset=0):
    if len(packet) < HEADER_SIZE:
        raise PacketError("truncated frame header")
    fields = HEADER.unpack_from(packet)
    magic_words = fields[:4]
    if packet[:8] != MAGIC:
        raise PacketError("bad magic word")
    (version, total_length, platform, frame_number, time_cpu_cycles,
     num_detected_obj, num_tlvs, subframe_number) = fields[4:]
    if total_length != len(packet):
        raise PacketError(f"totalPacketLen {total_length} != frame bytes {len(packet)}")
    if total_length < HEADER_SIZE or total_length > MAX_PACKET_SIZE:
        raise PacketError("totalPacketLen outside safe range")
    if total_length % PACKET_ALIGNMENT:
        raise PacketError("totalPacketLen is not 32-byte aligned")

    cursor = HEADER_SIZE
    tlvs = []
    frame_points = []
    for tlv_index in range(num_tlvs):
        if cursor + TLV_HEADER.size > total_length:
            raise PacketError(f"TLV {tlv_index} header crosses packet boundary")
        tlv_type, tlv_length = TLV_HEADER.unpack_from(packet, cursor)
        cursor += TLV_HEADER.size
        end = cursor + tlv_length
        if end > total_length:
            raise PacketError(f"TLV {tlv_index} payload crosses packet boundary")
        payload = packet[cursor:end]
        tlv_record = {"index": tlv_index, "type": tlv_type, "length": tlv_length}
        if tlv_type == TLV_TYPE_COMPRESSED_POINTS:
            points, units = parse_compressed_points(payload, num_detected_obj)
            frame_points.extend(points)
            tlv_record["decoded"] = "compressed_detected_points"
            tlv_record["units"] = units
            tlv_record["point_count"] = len(points)
        else:
            # Unknown/unsupported payload is bounded by its official TLV length.
            tlv_record["decoded"] = "skipped"
        tlvs.append(tlv_record)
        cursor = end

    padding = total_length - cursor
    if padding < 0 or padding >= PACKET_ALIGNMENT:
        raise PacketError(f"invalid padding length {padding}")
    return {
        "stream_offset": stream_offset,
        "magic_words": list(magic_words),
        "version": version,
        "total_packet_len": total_length,
        "platform": platform,
        "frame_number": frame_number,
        "time_cpu_cycles": time_cpu_cycles,
        "num_detected_obj": num_detected_obj,
        "num_tlvs": num_tlvs,
        "subframe_number": subframe_number,
        "padding_bytes": padding,
        "tlvs": tlvs,
        "points": frame_points,
    }


def parse_stream(data):
    frames = []
    warnings = []
    damaged = 0
    cursor = 0
    while True:
        position = data.find(MAGIC, cursor)
        if position < 0:
            break
        if position + HEADER_SIZE > len(data):
            warnings.append(f"offset {position}: truncated frame header")
            damaged += 1
            break
        total_length = struct.unpack_from("<I", data, position + 12)[0]
        if (total_length < HEADER_SIZE or total_length > MAX_PACKET_SIZE or
                total_length % PACKET_ALIGNMENT):
            warnings.append(f"offset {position}: invalid totalPacketLen {total_length}")
            damaged += 1
            cursor = position + 1
            continue
        end = position + total_length
        if end > len(data):
            warnings.append(
                f"offset {position}: truncated packet needs {total_length}, "
                f"has {len(data)-position} bytes"
            )
            damaged += 1
            break
        try:
            frame = parse_packet(data[position:end], position)
        except PacketError as exc:
            warnings.append(f"offset {position}: {exc}")
            damaged += 1
            cursor = position + 1
            continue
        frames.append(frame)
        cursor = end
    return frames, damaged, warnings


def choose_input(paths):
    files = []
    for value in paths:
        path = Path(value)
        if path.is_file():
            files.append(path)
    if not files:
        raise FileNotFoundError("no input raw file")
    return max(files, key=lambda p: p.stat().st_mtime)


def write_outputs(input_path, frames, damaged, warnings, magic_count):
    logs = Path("logs")
    json_path = logs / "parsed_frames.json"
    csv_path = logs / "detected_points.csv"
    document = {
        "input_file": str(input_path.resolve()),
        "magic_word_count": magic_count,
        "parsed_frame_count": len(frames),
        "damaged_or_incomplete_frame_count": damaged,
        "warnings": warnings,
        "frames": frames,
    }
    json_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    columns = ["timestamp_or_frame", "frame_number", "point_index", "x", "y",
               "z", "doppler", "snr", "noise"]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for frame in frames:
            for point in frame["points"]:
                writer.writerow({
                    "timestamp_or_frame": frame["frame_number"],
                    "frame_number": frame["frame_number"],
                    **{name: point[name] for name in columns[2:]},
                })
    return json_path, csv_path


def range_or_none(points, key):
    values = [point[key] for point in points]
    return [min(values), max(values)] if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()
    input_path = choose_input(args.inputs)
    data = input_path.read_bytes()
    magic_count = data.count(MAGIC)
    frames, damaged, warnings = parse_stream(data)
    json_path, csv_path = write_outputs(input_path, frames, damaged, warnings, magic_count)
    points = [point for frame in frames for point in frame["points"]]

    for frame in frames:
        print(f"frame {frame['frame_number']}: {len(frame['points'])} points")
    summary = {
        "input_file": str(input_path.resolve()),
        "magic_word_count": magic_count,
        "parsed_frame_count": len(frames),
        "damaged_or_incomplete_frame_count": damaged,
        "total_detected_points": len(points),
        "average_points_per_frame": len(points) / len(frames) if frames else 0,
        "x_range": range_or_none(points, "x"),
        "y_range": range_or_none(points, "y"),
        "z_range": range_or_none(points, "z"),
        "doppler_range": range_or_none(points, "doppler"),
        "snr_range": range_or_none(points, "snr"),
        "first_10_points": points[:10],
        "json_output": str(json_path.resolve()),
        "csv_output": str(csv_path.resolve()),
        "warnings": warnings,
    }
    print(json.dumps(summary, indent=2))
    return 0 if frames else 1


if __name__ == "__main__":
    sys.exit(main())
