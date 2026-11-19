# power.py - keep the PC awake while downloading, and sleep or shut down when the queue is done

from __future__ import annotations

import ctypes
import subprocess
import sys

from gfgmd.core.platform import hidden_window_flags
from gfgmd.utils.logging import write_log

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    """Stop Windows from sleeping while downloads run (the screen may still turn off)."""
    if sys.platform != "win32":
        return
    flags = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if on else 0)
    ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))


def perform(action: str) -> bool:
    """Sleep, hibernate, or shut down the PC; True when Windows accepted the request."""
    if sys.platform != "win32":
        return False
    try:
        if action in ("sleep", "hibernate"):
            # SetSuspendState(hibernate, force, wake events disabled)
            return bool(ctypes.windll.powrprof.SetSuspendState(action == "hibernate", False, False))
        if action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=True, creationflags=hidden_window_flags())
            return True
    except (OSError, subprocess.CalledProcessError) as error:
        write_log(f"Could not {action}: {error}", "critical")
    return False
