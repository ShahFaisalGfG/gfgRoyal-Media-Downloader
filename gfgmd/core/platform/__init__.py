"""Operating-system pieces of process handling, with a Windows and a POSIX implementation."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    from gfgmd.core.platform.win_job import ProcessGroup
else:
    from gfgmd.core.platform.posix import ProcessGroup

__all__ = ["ProcessGroup", "hidden_window_flags", "hide_folder"]

_FILE_ATTRIBUTE_HIDDEN = 0x2
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def hidden_window_flags() -> int:
    """Creation flags that keep a console program from flashing a window (0 off Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def hide_folder(path: Path) -> None:
    """Mark a folder hidden in Explorer; elsewhere its leading dot already hides it.

    The app's working folders (.archives, .incomplete) sit next to the downloads; hidden, they stay
    out of the way. A folder Windows won't mark (a network share, say) is left as it is.
    """
    if sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    attributes = kernel32.GetFileAttributesW(str(path))
    if attributes != _INVALID_FILE_ATTRIBUTES and not attributes & _FILE_ATTRIBUTE_HIDDEN:
        kernel32.SetFileAttributesW(str(path), attributes | _FILE_ATTRIBUTE_HIDDEN)
