# cdp.py - a minimal WebSocket client for the Chrome DevTools Protocol on 127.0.0.1 (stdlib only)
#
# Used once per sign-in to ask a headless browser for its cookies (Storage.getCookies) and to close
# it. Only loopback connections are made; frames from the client are masked as RFC 6455 requires.

from __future__ import annotations

import base64
import json
import os
import socket
import struct
from typing import Any
from urllib.parse import urlsplit

MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class CdpError(Exception):
    """The browser's debugging connection failed or answered with an error."""


class CdpClient:
    """One WebSocket connection to a browser's DevTools endpoint."""

    def __init__(self, url: str, timeout: float = 20.0) -> None:
        parts = urlsplit(url)
        if parts.scheme != "ws" or parts.hostname not in ("127.0.0.1", "localhost") or not parts.port:
            raise CdpError("Only a local DevTools address may be used")
        self._sock = socket.create_connection(("127.0.0.1", parts.port), timeout=timeout)
        self._buffer = b""
        self._next_id = 1
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (f"GET {parts.path or '/'} HTTP/1.1\r\nHost: 127.0.0.1:{parts.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self._sock.sendall(request.encode("ascii"))
        head = self._read_until(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise CdpError("The browser refused the DevTools connection")

    def close(self) -> None:
        """Close the socket."""
        try:
            self._sock.close()
        except OSError:
            pass

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one command and return its result, skipping unrelated events."""
        message_id = self._next_id
        self._next_id += 1
        self._send(json.dumps({"id": message_id, "method": method, "params": params or {}}).encode("utf-8"))
        while True:
            reply = json.loads(self._receive())
            if reply.get("id") != message_id:
                continue
            if "error" in reply:
                raise CdpError(str(reply["error"].get("message", reply["error"])))
            return reply.get("result", {})

    def send_only(self, method: str) -> None:
        """Send a command without waiting (Browser.close ends the connection)."""
        self._send(json.dumps({"id": self._next_id, "method": method}).encode("utf-8"))
        self._next_id += 1

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CdpError("The browser closed the DevTools connection")
            self._buffer += chunk
        head, _, self._buffer = self._buffer.partition(marker)
        return head

    def _read_exact(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(max(65536, count - len(self._buffer)))
            if not chunk:
                raise CdpError("The browser closed the DevTools connection")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _send(self, payload: bytes, opcode: int = 0x1) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def _receive(self) -> bytes:
        """One whole message (continuation frames joined); answers pings."""
        message = b""
        while True:
            first, second = self._read_exact(2)
            opcode, final = first & 0x0F, bool(first & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > MAX_MESSAGE_BYTES or len(message) + length > MAX_MESSAGE_BYTES:
                raise CdpError("The browser sent an unexpectedly large message")
            mask = self._read_exact(4) if second & 0x80 else b""
            payload = self._read_exact(length)
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 0x8:
                raise CdpError("The browser closed the DevTools connection")
            if opcode == 0x9:
                self._send(payload, 0xA)
                continue
            if opcode in (0x1, 0x2, 0x0):
                message += payload
                if final:
                    return message
