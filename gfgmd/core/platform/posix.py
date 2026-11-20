"""Run a program and every process it starts in its own session, so one signal ends them all."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Mapping, Sequence


class ProcessGroup:
    """One program and its descendants, started together and killed together."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[bytes] | None = None

    def launch(self, argv: Sequence[str], env: Mapping[str, str] | None = None,
               cwd: str | None = None, capture: bool = True,
               inherit: Sequence[int] = ()) -> subprocess.Popen[bytes]:
        """Start argv in a new session (stdout and stderr piped when `capture`); `inherit` lists file
        descriptors it keeps besides its standard ones."""
        output = subprocess.PIPE if capture else subprocess.DEVNULL
        process = subprocess.Popen(
            list(argv), stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            env=dict(env) if env is not None else None, cwd=cwd, start_new_session=True, pass_fds=tuple(inherit),
        )
        self.process = process
        return process

    def kill(self) -> None:
        """End the program and everything in its session."""
        if self.process is None or self.process.poll() is not None or sys.platform == "win32":
            return
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # already gone

    def close(self) -> None:
        """Nothing to release on POSIX; the session ends with its processes."""
