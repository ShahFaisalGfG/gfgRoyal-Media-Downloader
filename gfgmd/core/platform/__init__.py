"""Operating-system pieces of process handling, with a Windows and a POSIX implementation."""

from __future__ import annotations

import subprocess
import sys

if sys.platform == "win32":
    from gfgmd.core.platform.win_job import ProcessGroup
else:
    from gfgmd.core.platform.posix import ProcessGroup

__all__ = ["ProcessGroup", "hidden_window_flags"]


def hidden_window_flags() -> int:
    """Creation flags that keep a console program from flashing a window (0 off Windows)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
