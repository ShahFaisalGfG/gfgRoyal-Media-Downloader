"""Run one external program, hand each output line to a callback, and stop it on request."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import IO

from gfgmd.core.platform import ProcessGroup

# A line longer than this is dropped rather than kept growing (a runaway program printing without
# newlines); yt-dlp's own lines, including the JSON this app asks for, are far shorter.
MAX_LINE_BYTES = 1024 * 1024
_READ_SIZE = 64 * 1024

LineHandler = Callable[[str, str], object]  # (stream name "out" or "err", line); result ignored
# How a program is run: run_to_completion, or a stand-in a test gives (command, on_line, stop) -> (code, killed).
Runner = Callable[..., tuple[int, bool]]


def child_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """This process's environment with UTF-8 output forced for Python-based tools such as yt-dlp."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


class ProcessRunner:
    """Start argv once; `on_line` receives every stdout and stderr line, from reader threads."""

    def __init__(self, argv: Sequence[str], on_line: LineHandler, env: Mapping[str, str] | None = None,
                 cwd: str | None = None, max_line_bytes: int = MAX_LINE_BYTES) -> None:
        self._argv = list(argv)
        self._on_line = on_line
        self._max_line = max_line_bytes
        self._env = child_environment(env)
        self._cwd = cwd
        self._group: ProcessGroup | None = None
        self._readers: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._killed = False

    @property
    def killed(self) -> bool:
        """True once stop() ended the program."""
        return self._killed

    def start(self) -> None:
        """Launch the program; raises OSError when it can't be started."""
        group = ProcessGroup()
        try:
            process = group.launch(self._argv, self._env, self._cwd)
        except OSError:
            group.close()
            raise
        with self._lock:
            self._group = group
            if self._killed:  # stop() came while launching
                group.kill()
        assert process.stdout is not None and process.stderr is not None
        self._readers = [
            threading.Thread(target=self._read, args=(process.stdout, "out"), daemon=True, name="gfgmd-out"),
            threading.Thread(target=self._read, args=(process.stderr, "err"), daemon=True, name="gfgmd-err"),
        ]
        for reader in self._readers:
            reader.start()

    def wait(self) -> int:
        """Wait for the program and its output to end; returns the exit code."""
        group = self._group
        if group is None or group.process is None:
            raise RuntimeError("The program was not started")
        while True:
            # Short waits keep Ctrl+C responsive; an endless wait on Windows can't be interrupted.
            try:
                code = group.process.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                continue
        for reader in self._readers:
            reader.join()
        group.close()
        return code

    def stop(self) -> None:
        """End the program and every process it started; safe to call from any thread, any time."""
        with self._lock:
            self._killed = True
            group = self._group
        if group is not None:
            group.kill()

    def _read(self, stream: IO[bytes], name: str) -> None:
        """Split a pipe into lines on "\\n" and "\\r" (ffmpeg redraws progress with "\\r").

        Only each new chunk is split, and an unfinished line is kept in pieces, so a line of many
        megabytes (a long playlist's JSON) costs time in proportion to its size. A line longer than
        the limit is skipped to its end.
        """
        pending: list[bytes] = []  # the pieces of the line not finished yet
        size = 0
        skipping = False
        try:
            while True:
                chunk = stream.read1(_READ_SIZE) if hasattr(stream, "read1") else stream.read(_READ_SIZE)  # type: ignore[attr-defined]
                if not chunk:
                    break
                *lines, rest = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
                if lines:
                    first = b"".join([*pending, lines[0]])
                    if not skipping:
                        self._deliver(name, first)
                    for line in lines[1:]:
                        self._deliver(name, line)
                    pending, size, skipping = [], 0, False
                if rest:
                    pending.append(rest)
                    size += len(rest)
                if size > self._max_line:
                    pending, size, skipping = [], 0, True
            if pending and not skipping:
                self._deliver(name, b"".join(pending))
        except (OSError, ValueError):
            pass  # the pipe closed while the program was being stopped
        finally:
            stream.close()

    def _deliver(self, name: str, raw: bytes) -> None:
        if not raw or len(raw) > self._max_line:
            return
        self._on_line(name, raw.decode("utf-8", errors="replace"))


def run_to_completion(argv: Sequence[str], on_line: LineHandler, stop_event: threading.Event | None = None,
                      env: Mapping[str, str] | None = None, cwd: str | None = None,
                      max_line_bytes: int = MAX_LINE_BYTES) -> tuple[int, bool]:
    """Run argv until it exits or `stop_event` is set; returns (exit code, stopped)."""
    runner = ProcessRunner(argv, on_line, env, cwd, max_line_bytes)
    runner.start()
    watcher: threading.Thread | None = None
    done = threading.Event()
    if stop_event is not None:
        def watch() -> None:
            while not done.is_set():
                if stop_event.wait(0.2):
                    runner.stop()
                    return
        watcher = threading.Thread(target=watch, daemon=True, name="gfgmd-stop")
        watcher.start()
    try:
        code = runner.wait()
    except BaseException:
        # Ctrl+C or an error while waiting: the program runs in its own session or job and would
        # otherwise outlive this one, so end it before passing the interruption on.
        runner.stop()
        raise
    finally:
        done.set()
        if watcher is not None:
            watcher.join()
    return code, runner.killed
