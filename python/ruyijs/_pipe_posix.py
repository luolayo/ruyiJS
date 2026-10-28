"""Bounded local Unix-domain transport using the existing little-endian frames."""

import socket
import struct
import tempfile
import time

MAX_FRAME = 16 * 1024 * 1024


class Pipe:
    def __init__(self):
        self._directory = self._listener = self._socket = None
        try:
            # macOS TMPDIR can exceed sockaddr_un.sun_path's 104-byte limit.
            # mkdtemp's private directory also restricts access to this endpoint.
            self._directory = tempfile.TemporaryDirectory(prefix="ruyijs-", dir="/tmp")
            self.name = self._directory.name + "/rpc.sock"
            self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._listener.bind(self.name)
            self._listener.listen(1)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ruyijs socket operation timed out")
        return remaining

    def connect(self, deadline, process=None):
        if self._listener is None:
            raise OSError("ruyijs socket is not listening")
        while True:
            if process is not None and process.poll() is not None:
                raise EOFError("ruyijs process exited before connecting")
            remaining = self._remaining(deadline)
            self._listener.settimeout(min(remaining, 0.05) if process is not None else remaining)
            try:
                self._socket, _ = self._listener.accept()
                break
            except TimeoutError:
                if process is None:
                    raise
        self._listener.close()
        self._listener = None

    def _read_exact(self, size, deadline):
        if self._socket is None:
            raise EOFError("ruyijs socket is not connected")
        chunks = []
        while size:
            self._socket.settimeout(self._remaining(deadline))
            data = self._socket.recv(min(size, 65536))
            if not data:
                raise EOFError("ruyijs socket closed during a frame")
            chunks.append(data)
            size -= len(data)
        return b"".join(chunks)

    def receive(self, deadline):
        size = struct.unpack("<I", self._read_exact(4, deadline))[0]
        if size == 0 or size > MAX_FRAME:
            raise ValueError("invalid ruyijs response frame length")
        return self._read_exact(size, deadline)

    def send(self, data, deadline):
        if not data or len(data) > MAX_FRAME:
            raise ValueError("ruyijs request exceeds frame bounds")
        if self._socket is None:
            raise EOFError("ruyijs socket is not connected")
        frame = memoryview(struct.pack("<I", len(data)) + data)
        while frame:
            self._socket.settimeout(self._remaining(deadline))
            count = self._socket.send(frame[:65536])
            if not count:
                raise EOFError("ruyijs socket closed during a write")
            frame = frame[count:]

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
