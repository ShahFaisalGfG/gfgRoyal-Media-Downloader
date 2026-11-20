"""Run a program and every process it starts inside one Windows Job Object.

yt-dlp starts ffmpeg for merging and live streams. Killing only yt-dlp would leave ffmpeg running
and holding the files open, so each download runs in a job with KILL_ON_JOB_CLOSE: terminating the
job, or this app dying for any reason, ends the whole tree. The program starts suspended and is
resumed only after it joins the job, so not even its first child can start outside it.
"""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes
from typing import Any, Mapping, Sequence

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
_CREATE_SUSPENDED = 0x00000004


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _api(name: str, restype: Any, *argtypes: Any) -> Any:
    function = getattr(_kernel32, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


_CreateJobObjectW = _api("CreateJobObjectW", wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
_SetInformationJobObject = _api("SetInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
                                wintypes.LPVOID, wintypes.DWORD)
_AssignProcessToJobObject = _api("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
_TerminateJobObject = _api("TerminateJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)
_CloseHandle = _api("CloseHandle", wintypes.BOOL, wintypes.HANDLE)
_CreateToolhelp32Snapshot = _api("CreateToolhelp32Snapshot", wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
_Thread32First = _api("Thread32First", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_ThreadEntry))
_Thread32Next = _api("Thread32Next", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(_ThreadEntry))
_OpenThread = _api("OpenThread", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_ResumeThread = _api("ResumeThread", wintypes.DWORD, wintypes.HANDLE)


def _error(action: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{action} failed: {ctypes.FormatError(code).strip()}")


class ProcessGroup:
    """One program and its descendants, started together and killed together."""

    def __init__(self) -> None:
        self._job = _CreateJobObjectW(None, None)
        if not self._job:
            raise _error("CreateJobObject")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _SetInformationJobObject(self._job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                        ctypes.byref(info), ctypes.sizeof(info)):
            error = _error("SetInformationJobObject")
            _CloseHandle(self._job)
            raise error
        self.process: subprocess.Popen[bytes] | None = None

    def launch(self, argv: Sequence[str], env: Mapping[str, str] | None = None,
               cwd: str | None = None, capture: bool = True,
               inherit: Sequence[int] = ()) -> subprocess.Popen[bytes]:
        """Start argv suspended (stdout and stderr piped when `capture`), put it in the job, then resume it.

        `inherit` lists inheritable handles the program gets besides its standard ones (and no others).
        """
        output = subprocess.PIPE if capture else subprocess.DEVNULL
        flags = subprocess.CREATE_NO_WINDOW | _CREATE_SUSPENDED
        startup = None
        if inherit:
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": list(inherit)}
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            env=dict(env) if env is not None else None, cwd=cwd, creationflags=flags, startupinfo=startup,
        )
        self.process = process
        handle = int(process._handle)  # type: ignore[attr-defined]  # the process handle Popen keeps
        if not _AssignProcessToJobObject(self._job, handle):
            error = _error("AssignProcessToJobObject")
            process.kill()
            raise error
        _resume_threads(process.pid)
        return process

    def kill(self) -> None:
        """End the program and everything it started."""
        if self._job:
            _TerminateJobObject(self._job, 1)

    def close(self) -> None:
        """Release the job; any process still in it is ended (KILL_ON_JOB_CLOSE)."""
        if self._job:
            _CloseHandle(self._job)
            self._job = None


def _resume_threads(pid: int) -> None:
    """Resume every thread of a process started suspended."""
    snapshot = _CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE_VALUE or not snapshot:
        raise _error("CreateToolhelp32Snapshot")
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(_ThreadEntry)
        resumed = 0
        more = _Thread32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = _OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread:
                    _ResumeThread(thread)
                    _CloseHandle(thread)
                    resumed += 1
            more = _Thread32Next(snapshot, ctypes.byref(entry))
        if not resumed:
            raise OSError(f"Could not resume process {pid}")
    finally:
        _CloseHandle(snapshot)
