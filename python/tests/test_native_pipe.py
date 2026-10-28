"""Compile and run real ARM64 C++ Pipe endpoints against Python sockets."""

from pathlib import Path
import selectors
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

from ruyijs import Context
from ruyijs._pipe_posix import MAX_FRAME, Pipe

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin", "macOS native transport")
class NativePipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="ruyijs-native-", dir="/tmp")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.executable = Path(cls.directory.name) / "pipe-peer"
        subprocess.run([
            "xcrun", "clang++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I" + str(ROOT / "src"), str(Path(__file__).with_name("native_pipe_peer.cpp")),
            *map(str, sorted((ROOT / "src/runtime").glob("pipe*.cpp"))),
            "-o", str(cls.executable),
        ], check=True, capture_output=True, text=True, timeout=60)

    def start_peer(self, mode, path):
        process = subprocess.Popen([str(self.executable), mode, str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop_peer, process)
        return process

    @staticmethod
    def stop_peer(process):
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()

    @staticmethod
    def read_frame(peer):
        def exact(size):
            data = b""
            while len(data) < size:
                part = peer.recv(size - len(data))
                if not part:
                    raise EOFError("native peer closed")
                data += part
            return data
        return exact(struct.unpack("<I", exact(4))[0])

    def test_python_to_native_sync_and_async(self):
        for mode in ("client", "async-client"):
            with self.subTest(mode=mode):
                pipe = Pipe()
                self.addCleanup(pipe.close)
                process = self.start_peer(mode, pipe.name)
                pipe.connect(time.monotonic() + 3)
                for payload in ("中文\x00🦊".encode(), bytes(range(256)) * 1024, b"x" * MAX_FRAME, b"quit"):
                    pipe.send(payload, time.monotonic() + 5)
                    self.assertEqual(pipe.receive(time.monotonic() + 5), payload)
                self.assertEqual(process.wait(timeout=3), 0)

    def native_server(self, mode):
        directory = tempfile.TemporaryDirectory(prefix="ruyijs-server-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "rpc.sock"
        process = self.start_peer(mode, path)
        self.expect_line(process, b"ready\n")
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(peer.close)
        peer.settimeout(3)
        peer.connect(str(path))
        return path, process, peer

    def expect_line(self, process, line):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(3), "native peer did not acknowledge")
        self.assertEqual(process.stdout.readline(), line)

    def test_native_server_handles_fragmented_frames_and_cleans_path(self):
        for mode in ("server", "async-server"):
            with self.subTest(mode=mode):
                path, process, peer = self.native_server(mode)
                payload = "fragmented 中文".encode()
                frame = struct.pack("<I", len(payload)) + payload
                for byte in frame:
                    peer.sendall(bytes([byte]))
                    time.sleep(0.001)
                self.assertEqual(self.read_frame(peer), payload)
                peer.sendall(b"\x04\x00\x00\x00quit")
                self.assertEqual(self.read_frame(peer), b"quit")
                self.assertEqual(process.wait(timeout=3), 0)
                self.assertFalse(path.exists())

    def test_native_async_rejects_invalid_lengths(self):
        for size in (0, MAX_FRAME + 1):
            with self.subTest(size=size):
                _, process, peer = self.native_server("async-server")
                peer.sendall(struct.pack("<I", size))
                self.assertEqual(process.wait(timeout=3), 20)

    def test_native_write_after_disconnect_does_not_raise_sigpipe(self):
        _, process, peer = self.native_server("disconnect")
        self.expect_line(process, b"accepted\n")
        peer.close()
        self.assertEqual(process.wait(timeout=3), 0)

    def test_queue_limits_and_close_before_connect(self):
        path = Path(self.directory.name) / "queue.sock"
        process = self.start_peer("queue", path)
        self.assertEqual(process.wait(timeout=3), 0)
        self.assertFalse(path.exists())

    def test_failed_bind_does_not_remove_existing_path(self):
        path = Path(self.directory.name) / "existing"
        path.write_text("owned by caller")
        self.addCleanup(path.unlink)
        process = self.start_peer("collision", path)
        self.assertEqual(process.wait(timeout=3), 0)
        self.assertEqual(path.read_text(), "owned by caller")

    def test_context_launch_and_close_with_native_transport_peer(self):
        with Context(shell=self.executable, timeout=3) as context:
            process = context._process
            path = Path(context._pipe.name)
            self.assertFalse(context.closed)
            self.assertIsNone(process.poll())
        self.assertTrue(context.closed)
        self.assertEqual(process.returncode, 0)
        self.assertFalse(path.parent.exists())
