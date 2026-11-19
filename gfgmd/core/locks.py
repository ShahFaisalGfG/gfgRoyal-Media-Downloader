"""An exclusive lock shared between processes (the app and the command-line tool)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import TracebackType
from typing import IO


class FileLock:
    """Hold `<path>.lock` exclusively; the operating system releases it if the holder dies."""

    def __init__(self, path: Path, timeout: float | None = None) -> None:
        self._path = path.with_name(path.name + ".lock")
        self._timeout = timeout
        self._handle: IO[bytes] | None = None

    @property
    def lock_path(self) -> Path:
        """The lock file."""
        return self._path

    def acquire(self) -> bool:
        """Take the lock, waiting up to the timeout (None waits forever); True when held."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")  # noqa: SIM115 - held until release()
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        while True:
            if _try_lock(handle):
                self._handle = handle
                return True
            if deadline is not None and time.monotonic() >= deadline:
                handle.close()
                return False
            time.sleep(0.25)

    def release(self) -> None:
        """Release the lock if held."""
        if self._handle is None:
            return
        _unlock(self._handle)
        self._handle.close()
        self._handle = None

    def __enter__(self) -> FileLock:
        if not self.acquire():
            raise TimeoutError(f"{self._path.stem} is in use by another download")
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle: IO[bytes]) -> None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # the handle closes next, which releases the lock anyway
else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
