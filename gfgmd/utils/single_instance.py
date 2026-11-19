# single_instance.py - one window per user session; later launches hand their links to it
#
# The first launch listens on a local pipe. A later launch connects, sends its request as one line
# of JSON, and exits once the window answers "OK"; with no answer within _ANSWER_MS it opens its own
# window, so its files are never lost. The window answers at once but holds the requests until it
# has loaded (attach()), and drops a request whose sender stopped waiting, which has already opened
# the files itself.
# On Windows two QLocalServers can listen on one pipe name, so a named mutex turns "try to send,
# else listen" into one step: simultaneous launches (several files opened with Enter) end with one
# window. The pipe name carries the user's SID and session id, only this user may connect, and a
# sender writes only to a pipe served by its own account, so another account can't take the name
# and read the paths.

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from gfgmd.utils.launch import APP_PREFIX, LaunchRequest, own_sid, pipe_name, pipe_server_sid
from gfgmd.utils.logging import write_log

# Inno Setup's AppMutex waits while either exists, so the installers never replace a running copy.
APP_MUTEXES = ("gfgRoyalMediaDownloaderAppMutex", "Global\\gfgRoyalMediaDownloaderAppMutex")
_CONNECT_MS = 2000
_ANSWER_MS = 10_000      # how long a later launch waits for the window to take its request
_LOCK_MS = 30_000        # longer than one sender holds the lock: connect + _ANSWER_MS
_ACK_WRITE_MS = 1000
_ACK = b"OK\n"
# Everyone may open the installers' mutexes to wait on them (SYNCHRONIZE) and nothing more, so an
# installer running in another session or as another account still sees a running copy.
_APP_MUTEX_SDDL = "D:(A;;0x00100000;;;WD)"
_SDDL_REVISION_1 = 1
_SYNCHRONIZE = 0x00100000

_WAIT_OBJECT_0 = 0x0
_WAIT_ABANDONED = 0x80
_ASFW_ANY = 0xFFFFFFFF

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _api(dll: ctypes.WinDLL, name: str, restype: Any, *argtypes: Any) -> Any:
    """A function of dll with its result and argument types declared."""
    function = getattr(dll, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


_CloseHandle = _api(_kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
_LocalFree = _api(_kernel32, "LocalFree", wintypes.HLOCAL, wintypes.HLOCAL)
_CreateMutexW = _api(_kernel32, "CreateMutexW", wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_CreateMutexExW = _api(_kernel32, "CreateMutexExW", wintypes.HANDLE,
                       wintypes.LPVOID, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
_ConvertSddl = _api(_advapi32, "ConvertStringSecurityDescriptorToSecurityDescriptorW", wintypes.BOOL,
                    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG))


class _SecurityAttributes(ctypes.Structure):
    """SECURITY_ATTRIBUTES for CreateMutexW."""

    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                ("bInheritHandle", wintypes.BOOL)]
_WaitForSingleObject = _api(_kernel32, "WaitForSingleObject", wintypes.DWORD, wintypes.HANDLE, wintypes.DWORD)
_ReleaseMutex = _api(_kernel32, "ReleaseMutex", wintypes.BOOL, wintypes.HANDLE)
_AllowSetForegroundWindow = _api(_user32, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)

# Handles of APP_MUTEXES, open until the process exits.
_app_mutexes: list[int] = []


def hold_app_mutexes() -> None:
    """Create the mutexes the installers check (AppMutex) and keep them until this process exits.

    Creating the Global one can be refused in some sessions; the installers then see the other one.
    """
    descriptor = wintypes.LPVOID()
    if not _ConvertSddl(_APP_MUTEX_SDDL, _SDDL_REVISION_1, ctypes.byref(descriptor), None):
        write_log(f"Could not build the installer mutex access rules: {ctypes.WinError(ctypes.get_last_error())}",
                  "critical")
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
    security = ctypes.cast(ctypes.pointer(attributes), wintypes.LPVOID) if descriptor else None
    try:
        for name in APP_MUTEXES:
            # Asking only for SYNCHRONIZE (all the access rules grant) also opens one that another
            # app window or session made; CreateMutexW would ask for full access and be refused.
            handle = _CreateMutexExW(security, name, 0, _SYNCHRONIZE)
            if handle:
                _app_mutexes.append(handle)
            else:
                write_log(f"Could not create the mutex {name}: {ctypes.WinError(ctypes.get_last_error())}", "critical")
    finally:
        if descriptor:
            _LocalFree(descriptor)


def release_app_mutexes() -> None:
    """Let go of the installer mutexes early: an update's installer waits for them as the app exits."""
    while _app_mutexes:
        _CloseHandle(_app_mutexes.pop())


class SingleInstance(QObject):
    """Routes later launches to the first window of this user session."""

    # A later launch's files, as (mode, paths).
    filesReceived = Signal(str, list)
    # Every later launch, with or without files: the window comes to the front.
    activationRequested = Signal()
    # A message a later launch has for the user (paths it couldn't find, say).
    noticeReceived = Signal(str)

    def __init__(self, prefix: str = APP_PREFIX, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sid = own_sid()
        account = self._sid or os.environ.get("USERNAME", "user")
        self._pipe_name = pipe_name(prefix)
        self._mutex_name = f"Local\\{prefix}-instance-{account}"
        self._server: QLocalServer | None = None
        self._inboxes: dict[QLocalSocket, bytearray] = {}
        self._pending: list[LaunchRequest] = []
        self._attached = False

    def try_forward(self, request: LaunchRequest) -> bool:
        """Hand the launch to the open app window and return True, or return False to open a window.

        With no window to hand it to, this process starts listening for later launches.
        """
        with _named_mutex(self._mutex_name):
            sock = QLocalSocket()
            sock.connectToServer(self._pipe_name)
            if not sock.waitForConnected(_CONNECT_MS):
                if sock.error() == QLocalSocket.LocalSocketError.ServerNotFoundError:
                    self._listen()
                else:
                    write_log(f"The open app window can't be reached ({sock.errorString()}); "
                              "opening a new window", "critical")
                return False
            try:
                return self._send(sock, request)
            finally:
                sock.abort()

    def attach(self) -> None:
        """Deliver the launches that arrived while the window was loading, in order, then each as it comes."""
        self._attached = True
        pending, self._pending = self._pending, []
        for request in pending:
            self._deliver(request)

    def close(self) -> None:
        """Stop listening for later launches (on exit)."""
        if self._server is not None:
            self._server.close()
            self._server = None

    # ── Sending (a later launch) ─────────────────────────────────────────────

    def _send(self, sock: QLocalSocket, request: LaunchRequest) -> bool:
        """Write the request and wait for the window's answer; False when it doesn't come in time."""
        if not self._sid or pipe_server_sid(int(sock.socketDescriptor())) != self._sid:
            write_log("The app's pipe isn't served by this account; opening a new window", "critical")
            return False
        _AllowSetForegroundWindow(_ASFW_ANY)  # lets the open window come to the front
        deadline = time.monotonic() + _ANSWER_MS / 1000
        sock.write(request.encode())
        while sock.bytesToWrite() > 0:
            if not sock.waitForBytesWritten(_left_ms(deadline)):
                return _gave_up(sock)
        # The answer can arrive while the write is still being waited on; it is then already
        # buffered, and waitForReadyRead() only waits for more, so read before every wait.
        answer = bytearray(sock.readAll().data())
        while b"\n" not in answer:
            if not sock.waitForReadyRead(_left_ms(deadline)):
                return _gave_up(sock)
            answer += sock.readAll().data()
        return bytes(answer).startswith(_ACK)

    # ── Receiving (the window) ───────────────────────────────────────────────

    def _listen(self) -> None:
        """Start the server later launches connect to; only this user's processes may connect."""
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept)
        if server.listen(self._pipe_name):
            self._server = server
        else:
            write_log(f"Could not listen for later launches of the app: {server.errorString()}", "critical")
            server.deleteLater()

    def _accept(self) -> None:
        """Take every waiting connection; each one carries a single request line."""
        server = self._server
        while server is not None and server.hasPendingConnections():
            sock = server.nextPendingConnection()
            self._inboxes[sock] = bytearray()
            sock.readyRead.connect(partial(self._read, sock))
            sock.disconnected.connect(partial(self._closed, sock))

    def _read(self, sock: QLocalSocket) -> None:
        """Collect bytes until the request line is complete, then answer and queue it."""
        inbox = self._inboxes.get(sock)
        if inbox is None:
            return
        inbox += sock.readAll().data()
        line, complete, _rest = inbox.partition(b"\n")
        if not complete:
            return
        del self._inboxes[sock]
        try:
            request = LaunchRequest.decode(bytes(line))
        except ValueError as error:
            write_log(f"Could not read a message from another launch of the app: {error}", "critical")
            sock.disconnectFromServer()
            return
        sock.write(_ACK)
        if not sock.waitForBytesWritten(_ACK_WRITE_MS):
            write_log("A later launch of the app stopped waiting and opened its own window", "general")
            return
        if self._attached:
            self._deliver(request)
        else:
            self._pending.append(request)

    def _closed(self, sock: QLocalSocket) -> None:
        """Handle what a sender wrote just before hanging up, then free its socket."""
        self._read(sock)
        self._inboxes.pop(sock, None)
        sock.deleteLater()

    def _deliver(self, request: LaunchRequest) -> None:
        """Bring the window forward and hand it the request's files and notice."""
        self.activationRequested.emit()
        if request.mode and request.paths:
            self.filesReceived.emit(request.mode, list(request.paths))
        if request.notice:
            self.noticeReceived.emit(request.notice)


@contextmanager
def _named_mutex(name: str) -> Iterator[None]:
    """Hold the named mutex for a with-block, waiting up to _LOCK_MS for another launch to release it."""
    handle = _CreateMutexW(None, False, name)
    owned = bool(handle) and _WaitForSingleObject(handle, _LOCK_MS) in (_WAIT_OBJECT_0, _WAIT_ABANDONED)
    if not owned:
        write_log(f"Could not take the mutex {name}; going on without it", "critical")
    try:
        yield
    finally:
        if owned:
            _ReleaseMutex(handle)
        if handle:
            _CloseHandle(handle)


def _left_ms(deadline: float) -> int:
    """Milliseconds until deadline (0 once it has passed)."""
    return max(0, int((deadline - time.monotonic()) * 1000))


def _gave_up(sock: QLocalSocket) -> bool:
    """Log that the window didn't take the request in time and return False (open a new window)."""
    write_log(f"The open app window didn't answer in {_ANSWER_MS // 1000} s ({sock.errorString()}); "
              "opening a new window", "critical")
    return False
