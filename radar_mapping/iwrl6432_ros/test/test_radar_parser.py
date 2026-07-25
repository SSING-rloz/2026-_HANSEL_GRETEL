#!/usr/bin/env python3
"""Boundary tests adapted from the offline parser validation workspace."""

import struct
import unittest

from iwrl6432_ros import radar_parser as parser


def packet_with_tlv(tlv_type=999, payload=b"abc"):
    used = parser.HEADER_SIZE + parser.TLV_HEADER.size + len(payload)
    total = ((used + 31) // 32) * 32
    header = parser.HEADER.pack(
        0x0102, 0x0304, 0x0506, 0x0708,
        0x05050402, total, 0xA6432, 7, 0, 0, 1, 0xFFFFFFFF,
    )
    return (header + parser.TLV_HEADER.pack(tlv_type, len(payload)) + payload +
            bytes(total - used))


class ParserBoundaryTests(unittest.TestCase):
    def test_packet_length_boundary_rejected(self):
        packet = bytearray(packet_with_tlv())
        struct.pack_into("<I", packet, 12, len(packet) + 32)
        frames, damaged, _warnings = parser.parse_stream(bytes(packet))
        self.assertEqual(frames, [])
        self.assertEqual(damaged, 1)

    def test_truncated_packet_is_reported(self):
        packet = packet_with_tlv()
        frames, damaged, _warnings = parser.parse_stream(packet[:-1])
        self.assertEqual(frames, [])
        self.assertEqual(damaged, 1)

    def test_unknown_tlv_is_safely_skipped(self):
        frame = parser.parse_packet(packet_with_tlv())
        self.assertEqual(frame["tlvs"][0]["type"], 999)
        self.assertEqual(frame["tlvs"][0]["decoded"], "skipped")
        self.assertEqual(frame["points"], [])


if __name__ == "__main__":
    unittest.main()
