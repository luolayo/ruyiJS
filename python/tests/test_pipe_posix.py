"""Exercise the actual Unix socket transport, including deadline and frame failures."""

from pathlib import Path
import socket
import stat
import struct
import sys
import time
import unittest

from ruyijs._pipe_posix import MAX_FRAME, Pipe


@unittest.skipUnless(sys.platform == "darwin", "macOS transport")
class PipeTests(unittest.TestCase):
    def setUp(self):
        self.pipe = Pipe()
        self.addCleanup(self.pipe.close)

    def connect_peer(self):
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(peer.close)
        peer.settimeout(2)
        peer.connect(self.pipe.name)
        self.pipe.connect(time.monotonic() + 2)
        return peer

    def test_private_short_endpoint_and_idempotent_cleanup(self):
        directory = Path(self.pipe.name).parent
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertLess(len(self.pipe.name.encode()), 104)
        self.pipe.close()
        self.pipe.close()
        self.assertFalse(directory.exists())

    def test_connection_timeout(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.pipe.connect(start + 0.05)
        self.assertLess(time.monotonic() - start, 1)

    def test_frames_are_little_endian_and_preserve_bytes(self):
        peer = self.connect_peer()
        payload = "中文\x00🦊".encode()
        self.pipe.send(payload, time.monotonic() + 2)
        frame = b""
        while len(frame) < 4 + len(payload):
            frame += peer.recv(65536)
        self.assertEqual(frame, struct.pack("<I", len(payload)) + payload)
        peer.sendall(frame)
        self.assertEqual(self.pipe.receive(time.monotonic() + 2), payload)

    def test_coalesced_frames_remain_separate(self):
        peer = self.connect_peer()
        peer.sendall(b"\x01\x00\x00\x00a\x02\x00\x00\x00bc")
        self.assertEqual(self.pipe.receive(time.monotonic() + 2), b"a")
        self.assertEqual(self.pipe.receive(time.monotonic() + 2), b"bc")

    def test_partial_header_timeout(self):
        peer = self.connect_peer()
        peer.sendall(b"\x04\x00")
        with self.assertRaises(TimeoutError):
            self.pipe.receive(time.monotonic() + 0.05)

    def test_eof_inside_body(self):
        peer = self.connect_peer()
        peer.sendall(b"\x04\x00\x00\x00ab")
        peer.close()
        with self.assertRaises(EOFError):
            self.pipe.receive(time.monotonic() + 2)

    def test_invalid_incoming_lengths(self):
        peer = self.connect_peer()
        for length in (0, MAX_FRAME + 1, 0xFFFFFFFF):
            with self.subTest(length=length):
                peer.sendall(struct.pack("<I", length))
                with self.assertRaises(ValueError):
                    self.pipe.receive(time.monotonic() + 2)

    def test_invalid_outgoing_lengths(self):
        for payload in (b"", b"x" * (MAX_FRAME + 1)):
            with self.assertRaises(ValueError):
                self.pipe.send(payload, time.monotonic() + 2)

    def test_backpressure_respects_write_deadline(self):
        peer = self.connect_peer()
        peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.pipe.send(b"x" * MAX_FRAME, start + 0.1)
        self.assertLess(time.monotonic() - start, 1)

    def test_expired_deadline_does_not_consume_frame(self):
        peer = self.connect_peer()
        peer.sendall(b"\x01\x00\x00\x00x")
        with self.assertRaises(TimeoutError):
            self.pipe.receive(time.monotonic() - 1)
        self.assertEqual(self.pipe.receive(time.monotonic() + 2), b"x")

    def test_context_endpoints_are_isolated(self):
        other = Pipe()
        self.addCleanup(other.close)
        self.assertNotEqual(self.pipe.name, other.name)
        peer = self.connect_peer()
        self.pipe.close()
        self.assertEqual(peer.recv(1), b"")
        self.assertTrue(Path(other.name).exists())
