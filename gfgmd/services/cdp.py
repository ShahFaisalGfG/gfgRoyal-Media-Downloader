# cdp.py - a minimal Chrome DevTools Protocol client over the browser's own pipe (stdlib only)
#
# Used once per sign-in to ask a headless browser for its cookies (Storage.getCookies) and to close
# it. The browser is started with --remote-debugging-pipe and inherits two pipe handles
# (--remote-debugging-io-pipes on Windows), so it never listens on a port: no other program on the
# PC can reach it while it runs. Messages are JSON, each ended by a NUL byte.

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from typing import Any

MAX_MESSAGE_BYTES = 64 * 1024 * 1024


class CdpError(Exception):
    """The browser's debugging connection failed or answered with an error."""


class CdpPipe:
    """Two pipes to one browser: commands go in through one, answers come back through the other.

    Create it, start the browser with browser_args() and child_handles() inherited, then call
    started(); close() when done (the browser's ends are closed once it has them).
    """

    def __init__(self, timeout: float = 20.0) -> None:
        if sys.platform != "win32":
            raise CdpError("The browser's debugging pipe is set up for Windows only")
        import msvcrt  # Windows only; imported here so the module loads anywhere

        self._timeout = timeout
        self._next_id = 1
        self._messages: queue.Queue[bytes | None] = queue.Queue()
        self._to_browser_read, self._to_browser = os.pipe()
        self._from_browser, self._from_browser_write = os.pipe()
        # Every end still open here; each is closed once (a closed number may be reused by another file).
        self._open = {self._to_browser_read, self._to_browser, self._from_browser, self._from_browser_write}
        self._browser_handles = (msvcrt.get_osfhandle(self._to_browser_read),
                                 msvcrt.get_osfhandle(self._from_browser_write))
        for handle in self._browser_handles:
            os.set_handle_inheritable(handle, True)
        self._reader: threading.Thread | None = None

    def child_handles(self) -> tuple[int, int]:
        """The handles the browser inherits: the one it reads commands from, the one it answers on."""
        return self._browser_handles

    def browser_args(self) -> list[str]:
        """The switches that make the browser use these pipes instead of a port."""
        read, write = self._browser_handles
        return ["--remote-debugging-pipe", f"--remote-debugging-io-pipes={read},{write}"]

    def started(self) -> None:
        """The browser has its ends: close them here (so its exit ends the pipe) and start reading."""
        self._close(self._to_browser_read)
        self._close(self._from_browser_write)
        self._reader = threading.Thread(target=self._read, daemon=True, name="gfgmd-cdp-read")
        self._reader.start()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one command and return its result, skipping unrelated events."""
        message_id = self._send(method, params)
        while True:
            try:
                raw = self._messages.get(timeout=self._timeout)
            except queue.Empty as exc:
                raise CdpError("The browser didn't answer in time") from exc
            if raw is None:
                raise CdpError("The browser closed before answering; a window of this sign-in may still be open")
            reply = json.loads(raw)
            if reply.get("id") != message_id:
                continue
            if "error" in reply:
                raise CdpError(str(reply["error"].get("message", reply["error"])))
            return reply.get("result", {})

    def send_only(self, method: str) -> None:
        """Send a command without waiting (Browser.close ends the connection)."""
        self._send(method, None)

    def close(self) -> None:
        """Close every end still open here."""
        for fd in list(self._open):
            self._close(fd)

    def _close(self, fd: int) -> None:
        if fd in self._open:
            self._open.discard(fd)
            try:
                os.close(fd)
            except OSError:
                pass  # the browser side already went away

    def _send(self, method: str, params: dict[str, Any] | None) -> int:
        message_id = self._next_id
        self._next_id += 1
        payload = json.dumps({"id": message_id, "method": method, "params": params or {}}).encode("utf-8")
        try:
            os.write(self._to_browser, payload + b"\0")
        except OSError as exc:
            raise CdpError("The browser closed the debugging pipe") from exc
        return message_id

    def _read(self) -> None:
        """On its own thread: split what the browser writes into messages until it closes the pipe."""
        buffer = b""
        while True:
            try:
                chunk = os.read(self._from_browser, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                self._messages.put(None)
                return
            buffer += chunk
            if len(buffer) > MAX_MESSAGE_BYTES:
                self._messages.put(None)
                return
            while b"\0" in buffer:
                message, buffer = buffer.split(b"\0", 1)
                self._messages.put(message)
