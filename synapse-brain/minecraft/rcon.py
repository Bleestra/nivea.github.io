"""A minimal RCON client for the Minecraft server (the experimenter's console: /give, /tp, /setblock...)."""
import socket
import struct


class Rcon:
    def __init__(self, password, host="127.0.0.1", port=25575, timeout=5.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.id = 0
        if self._send(3, password)[0] == -1:
            raise PermissionError("RCON: wrong password")

    def _send(self, kind, text):
        self.id += 1
        data = struct.pack("<ii", self.id, kind) + text.encode("utf-8") + b"\x00\x00"
        self.s.sendall(struct.pack("<i", len(data)) + data)
        size = struct.unpack("<i", self._read(4))[0]
        rid, _ = struct.unpack("<ii", self._read(8))
        body = self._read(size - 8)
        return rid, body[:-2].decode("utf-8", "replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON closed")
            buf += chunk
        return buf

    def __call__(self, command):
        return self._send(2, command.lstrip("/"))[1]

    def close(self):
        self.s.close()
