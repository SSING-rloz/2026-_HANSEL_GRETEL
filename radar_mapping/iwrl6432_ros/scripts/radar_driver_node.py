#!/usr/bin/env python3
"""IWRL6432 UART to sensor_msgs/PointCloud2 ROS1 node."""

import errno
import fcntl
import math
import os
import select
import struct
import termios
import time

import rospy
from sensor_msgs.msg import PointCloud2, PointField
from std_msgs.msg import Header

from iwrl6432_ros import radar_parser


TIOCEXCL = 0x540C
TCGETS2 = 0x802C542A
TCSETS2 = 0x402C542B
CBAUD = 0x100F
BOTHER = 0x1000
TERMIOS2_FORMAT = "IIIIB19BII"
TERMIOS2_SIZE = struct.calcsize(TERMIOS2_FORMAT)
POINT_PACKER = struct.Struct("<6f")


class RadarDriver:
    def __init__(self):
        self.port = rospy.get_param("~port", "/dev/ttyACM0")
        self.config_file = rospy.get_param("~config_file")
        self.frame_id = rospy.get_param("~frame_id", "radar_link")
        self.min_snr = float(rospy.get_param("~min_snr", 0.0))
        self.min_range = float(rospy.get_param("~min_range", 0.0))
        self.max_range = float(rospy.get_param("~max_range", 20.0))
        self.z_min = float(rospy.get_param("~z_min", -10.0))
        self.z_max = float(rospy.get_param("~z_max", 10.0))
        self.fd = None
        self.running = False
        self.stream = bytearray()
        self.publisher = rospy.Publisher("/radar/points", PointCloud2, queue_size=10)

    @staticmethod
    def set_baud(fd, baud):
        if baud == 115200:
            attrs = termios.tcgetattr(fd)
            attrs[0] = 0
            attrs[1] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[3] = 0
            attrs[4] = termios.B115200
            attrs[5] = termios.B115200
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            return
        buffer = bytearray(TERMIOS2_SIZE)
        fcntl.ioctl(fd, TCGETS2, buffer, True)
        values = list(struct.unpack(TERMIOS2_FORMAT, buffer))
        values[0] = values[1] = values[3] = 0
        values[2] = ((values[2] & ~CBAUD) | BOTHER | termios.CS8 |
                     termios.CREAD | termios.CLOCAL)
        values[-2] = values[-1] = baud
        fcntl.ioctl(fd, TCSETS2, struct.pack(TERMIOS2_FORMAT, *values))

    def open(self):
        if self.port != "/dev/ttyACM0":
            rospy.logwarn("Configured port is %s (expected /dev/ttyACM0)", self.port)
        try:
            self.fd = os.open(
                self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
            )
            fcntl.ioctl(self.fd, TIOCEXCL)
            self.set_baud(self.fd, 115200)
        except OSError as exc:
            self.close()
            if exc.errno == errno.EBUSY:
                raise RuntimeError("UART port is busy: " + self.port) from exc
            raise
        quiet = self.drain_until_quiet(0.4, 1.5)
        if not quiet:
            rospy.logwarn("UART did not become quiet at 115200 baud; "
                          "discarding pending input and trying CLI commands")
            termios.tcflush(self.fd, termios.TCIFLUSH)
        if rospy.is_shutdown():
            raise rospy.ROSInterruptException("shutdown during UART synchronization")
        rospy.loginfo("Opened %s at 115200 baud, 8N1, no flow control", self.port)

    def read_available(self, timeout=0.05):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(self.fd, 65536)
        except BlockingIOError:
            return b""

    def drain_until_quiet(self, quiet, max_wait):
        deadline = time.monotonic() + max_wait
        last = time.monotonic()
        while (time.monotonic() - last < quiet and
               time.monotonic() < deadline and
               not rospy.is_shutdown()):
            if self.read_available(0.05):
                last = time.monotonic()
        return time.monotonic() - last >= quiet

    def write_line(self, command):
        payload = command.encode("ascii") + b"\r\n"
        offset = 0
        while offset < len(payload):
            try:
                offset += os.write(self.fd, payload[offset:])
            except BlockingIOError:
                select.select([], [self.fd], [], 0.2)
        termios.tcdrain(self.fd)

    def wait_done(self, timeout=1.5, preserve_binary=False):
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not rospy.is_shutdown():
            data.extend(self.read_available(min(0.05, deadline-time.monotonic())))
            lowered = bytes(data).lower()
            if any(word in lowered for word in
                   (b"error", b"invalid", b"not recognized", b"exception")):
                raise RuntimeError("CLI error: " + bytes(data).decode("ascii", "replace"))
            if b"done" in lowered:
                prompt_at = data.rfind(radar_parser.PROMPT if hasattr(radar_parser, "PROMPT") else b"mmwDemo:/>")
                if prompt_at >= 0:
                    end = prompt_at + len(b"mmwDemo:/>")
                    remainder = bytes(data[end:])
                    if preserve_binary:
                        self.stream.extend(remainder.lstrip(b"\r\n"))
                    return
        raise RuntimeError("CLI Done timeout: " + bytes(data).decode("ascii", "replace"))

    def load_commands(self):
        commands = []
        with open(self.config_file, "r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if line and not line.startswith("%"):
                    commands.append(line)
        return commands

    def configure_and_start(self):
        commands = self.load_commands()
        for index, command in enumerate(commands, 1):
            if rospy.is_shutdown():
                raise rospy.ROSInterruptException("shutdown before CFG completed")
            name = command.split()[0]
            rospy.loginfo("CFG %d/%d: %s", index, len(commands), command)
            self.write_line(command)
            if name == "baudRate":
                baud = int(command.split()[1], 0)
                self.set_baud(self.fd, baud)
                rospy.loginfo("Host UART switched immediately to %d baud", baud)
                # The transition can split/drop the textual Done response.
                time.sleep(0.15)
                continue
            if name == "sensorStart":
                self.wait_done(2.0, preserve_binary=True)
                self.running = True
                rospy.loginfo("sensorStart accepted; publishing /radar/points")
                return
            self.wait_done()
            time.sleep(0.1)
        raise RuntimeError("CFG ended without sensorStart")

    def filtered_points(self, points):
        output = []
        for point in points:
            radius = math.sqrt(point["x"]**2 + point["y"]**2 + point["z"]**2)
            if (point["snr"] >= self.min_snr and
                    self.min_range <= radius <= self.max_range and
                    self.z_min <= point["z"] <= self.z_max):
                output.append(point)
        return output

    def publish(self, frame):
        points = self.filtered_points(frame["points"])
        message = PointCloud2()
        message.header = Header(stamp=rospy.Time.now(), frame_id=self.frame_id)
        message.height = 1
        message.width = len(points)
        message.is_bigendian = False
        message.is_dense = True
        names = ("x", "y", "z", "doppler", "snr", "noise")
        message.fields = [
            PointField(name=name, offset=i*4, datatype=PointField.FLOAT32, count=1)
            for i, name in enumerate(names)
        ]
        message.point_step = POINT_PACKER.size
        message.row_step = message.point_step * message.width
        message.data = b"".join(
            POINT_PACKER.pack(
                point["x"], point["y"], point["z"], point["doppler"],
                point["snr"], point["noise"]
            ) for point in points
        )
        self.publisher.publish(message)
        rospy.logdebug("frame=%d points=%d", frame["frame_number"], len(points))

    def process_stream(self):
        while not rospy.is_shutdown():
            chunk = self.read_available(0.2)
            if chunk:
                self.stream.extend(chunk)
            while True:
                position = self.stream.find(radar_parser.MAGIC)
                if position < 0:
                    if len(self.stream) > 7:
                        del self.stream[:-7]
                    break
                if position:
                    del self.stream[:position]
                if len(self.stream) < radar_parser.HEADER_SIZE:
                    break
                total = struct.unpack_from("<I", self.stream, 12)[0]
                if (total < radar_parser.HEADER_SIZE or
                        total > radar_parser.MAX_PACKET_SIZE or
                        total % radar_parser.PACKET_ALIGNMENT):
                    rospy.logwarn("Invalid totalPacketLen=%d; resynchronizing", total)
                    del self.stream[0]
                    continue
                if len(self.stream) < total:
                    break
                packet = bytes(self.stream[:total])
                del self.stream[:total]
                try:
                    frame = radar_parser.parse_packet(packet)
                except radar_parser.PacketError as exc:
                    rospy.logwarn("Dropped malformed radar frame: %s", exc)
                    continue
                self.publish(frame)

    def stop_sensor(self):
        if self.fd is None:
            return
        try:
            self.write_line("sensorStop 0")
            rospy.loginfo("sensorStop 0 sent")
        except Exception as exc:
            rospy.logwarn("Could not send sensorStop during shutdown: %s", exc)

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def run(self):
        try:
            self.open()
            self.configure_and_start()
            self.process_stream()
        finally:
            self.stop_sensor()
            self.close()


if __name__ == "__main__":
    rospy.init_node("iwrl6432_radar_driver")
    driver = RadarDriver()
    try:
        driver.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as exc:
        rospy.logfatal("Radar driver stopped: %s", exc)
        driver.close()
        raise
