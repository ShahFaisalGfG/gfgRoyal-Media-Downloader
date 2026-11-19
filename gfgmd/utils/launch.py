# launch.py - the request a launch hands to the running app, and the pipe it travels through
#
# Standard library only, so the companion's native-messaging host (a small console program) can
# reach the running app without Qt. The app listens on a named pipe whose name carries the user's
# SID and session id (see single_instance.py); a sender writes only to a pipe served by its own
# account, so another account can't take the name and read the links or sign-in data.

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any

APP_PREFIX = "gfgRoyal-Media-Downloader"
_ACK = b"OK\n"
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class LaunchRequest:
    """What one launch asks for: a mode, its values (links, or a site and cookies), and a notice ("" if none)."""

    mode: str = ""
    paths: tuple[str, ...] = ()
    notice: str = ""

    def encode(self) -> bytes:
        """The request as one line of JSON (json.dumps escapes any newline inside a value)."""
        return json.dumps({"mode": self.mode, "paths": list(self.paths), "notice": self.notice}).encode("utf-8") + b"\n"

    @classmethod
    def decode(cls, line: bytes) -> LaunchRequest:
        """Parse a line written by encode(); raises ValueError for anything else."""
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("the message is not a JSON object")
        mode, paths, notice = payload.get("mode", ""), payload.get("paths", []), payload.get("notice", "")
        if not (isinstance(mode, str) and isinstance(notice, str) and isinstance(paths, list)
                and all(isinstance(path, str) for path in paths)):
            raise ValueError("the message has fields of the wrong type")
        return cls(mode, tuple(paths), notice)


if sys.platform == "win32":
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    def _api(dll: Any, name: str, restype: Any, *argtypes: Any) -> Any:
        """A function of dll with its result and argument types declared."""
        function = getattr(dll, name)
        function.restype = restype
        function.argtypes = argtypes
        return function

    _GetCurrentProcess = _api(_kernel32, "GetCurrentProcess", wintypes.HANDLE)
    _GetCurrentProcessId = _api(_kernel32, "GetCurrentProcessId", wintypes.DWORD)
    _ProcessIdToSessionId = _api(_kernel32, "ProcessIdToSessionId", wintypes.BOOL,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    _OpenProcess = _api(_kernel32, "OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _CloseHandle = _api(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    _LocalFree = _api(_kernel32, "LocalFree", wintypes.HLOCAL, wintypes.HLOCAL)
    _GetNamedPipeServerProcessId = _api(_kernel32, "GetNamedPipeServerProcessId", wintypes.BOOL,
                                        wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    _OpenProcessToken = _api(_advapi32, "OpenProcessToken", wintypes.BOOL,
                             wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    _GetTokenInformation = _api(_advapi32, "GetTokenInformation", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                                wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    _ConvertSidToStringSidW = _api(_advapi32, "ConvertSidToStringSidW", wintypes.BOOL,
                                   wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR))

    def session_id() -> int:
        """This process's Windows session id (0 if it can't be read)."""
        session = wintypes.DWORD()
        if _ProcessIdToSessionId(_GetCurrentProcessId(), ctypes.byref(session)):
            return session.value
        return 0

    def process_sid(process: int) -> str:
        """The string SID ("S-1-5-21-...") of the account a process runs as; raises OSError on failure."""
        token = wintypes.HANDLE()
        if not _OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            size = wintypes.DWORD()
            _GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            if not _GetTokenInformation(token, _TOKEN_USER, buffer, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.cast(buffer, ctypes.POINTER(wintypes.LPVOID))[0]  # TOKEN_USER starts with the SID pointer
            text = wintypes.LPWSTR()
            if not _ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return text.value or ""
            finally:
                _LocalFree(ctypes.cast(text, wintypes.HLOCAL))
        finally:
            _CloseHandle(token)

    def own_sid() -> str:
        """The SID of the account this process runs as, or "" if it can't be read."""
        try:
            return process_sid(_GetCurrentProcess())
        except OSError:
            return ""

    def pipe_server_sid(handle: int) -> str:
        """The SID of the account whose process serves a connected pipe handle, or "" if unknown."""
        pid = wintypes.ULONG()
        if not _GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
            return ""
        process = _OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return ""
        try:
            return process_sid(process)
        except OSError:
            return ""
        finally:
            _CloseHandle(process)
else:
    def session_id() -> int:
        """Sessions are a Windows idea; other systems use 0."""
        return 0

    def own_sid() -> str:
        """The user id stands in for a SID off Windows."""
        return str(os.getuid()) if hasattr(os, "getuid") else ""

    def pipe_server_sid(handle: int) -> str:
        """Not checked off Windows (no named pipes)."""
        return ""


def pipe_name(prefix: str = APP_PREFIX) -> str:
    """The pipe the running app listens on for this account and session."""
    account = own_sid() or os.environ.get("USERNAME", "user")
    return f"{prefix}-{account}-{session_id()}"


def send(request: LaunchRequest, timeout: float = 10.0, prefix: str = APP_PREFIX) -> bool:
    """Hand a request to the running app without Qt; True once it answered (Windows only)."""
    if sys.platform != "win32":
        return False
    path = "\\\\.\\pipe\\" + pipe_name(prefix)
    try:
        pipe = open(path, "r+b", buffering=0)  # noqa: SIM115 - closed below
    except OSError:
        return False
    answered = threading.Event()
    reply = bytearray()

    def read() -> None:
        try:
            while b"\n" not in reply:
                chunk = pipe.read(16)
                if not chunk:
                    break
                reply.extend(chunk)
        except OSError:
            pass
        answered.set()

    try:
        expected = own_sid()
        if not expected or pipe_server_sid(msvcrt.get_osfhandle(pipe.fileno())) != expected:
            return False
        pipe.write(request.encode())
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        answered.wait(timeout)
        return bytes(reply).startswith(_ACK)
    except OSError:
        return False
    finally:
        pipe.close()
