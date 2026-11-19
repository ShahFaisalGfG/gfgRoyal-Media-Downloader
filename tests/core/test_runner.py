"""The process runner: lines from both pipes, floods without deadlock, and whole-tree stops."""

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from gfgmd.core.runner import ProcessRunner, run_to_completion

HARDENED = ["--ignore-config", "--no-plugin-dirs", "--no-remote-components"]


def collect() -> tuple[list[tuple[str, str]], object]:
    lines: list[tuple[str, str]] = []
    lock = threading.Lock()

    def on_line(stream: str, line: str) -> None:
        with lock:
            lines.append((stream, line))
    return lines, on_line


def test_reads_both_streams(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Deliver stdout and stderr lines and return the exit code."""
    lines, on_line = collect()
    code, stopped = run_to_completion(
        fake_ytdlp + HARDENED + ["--paths", str(tmp_path), "--", "https://fake.test/private"], on_line)
    assert (code, stopped) == (1, False)
    assert any(stream == "err" and "Private video" in line for stream, line in lines)


def test_flood_of_output_does_not_deadlock(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Split on carriage returns, drop an oversized line, survive bad bytes and 10 MB of stderr."""
    lines, on_line = collect()
    started = time.monotonic()
    code, _ = run_to_completion(
        fake_ytdlp + HARDENED + ["--paths", str(tmp_path), "--download-archive", str(tmp_path / "a.txt"),
                                 "--", "https://fake.test/flood"], on_line)
    assert code == 0
    assert time.monotonic() - started < 60
    out = [line for stream, line in lines if stream == "out"]
    assert sum(1 for line in out if line.startswith("[download]")) == 20000
    assert not any(len(line) > 1024 * 1024 for _, line in lines)
    assert "bad bytes �� here" in out
    assert any(line.startswith("@@gfgr:file ") for line in out)


def test_stop_kills_the_whole_tree(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Stopping ends yt-dlp and every process it started (ffmpeg in real downloads)."""
    lines, on_line = collect()
    stop = threading.Event()
    state = Path(fake_ytdlp[-1])
    result: list[tuple[int, bool]] = []
    worker = threading.Thread(target=lambda: result.append(run_to_completion(
        fake_ytdlp + HARDENED + ["--paths", str(tmp_path), "--", "https://fake.test/slow"], on_line, stop)))
    worker.start()
    deadline = time.monotonic() + 30
    while not (state / "grandchild.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    grandchild = int((state / "grandchild.pid").read_text())
    stop.set()
    worker.join(30)
    assert result and result[0][1] is True
    assert not _alive(grandchild, timeout=10)


def test_start_failure_raises() -> None:
    """A program that doesn't exist raises OSError at start."""
    runner = ProcessRunner([os.path.join("no", "such", "program.exe")], lambda stream, line: None)
    with pytest.raises(OSError):
        runner.start()


def _alive(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _exists(pid):
            return False
        time.sleep(0.1)
    return _exists(pid)


def _exists(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(ctypes.c_void_p(handle), 0) != 0  # 0 = signaled (exited)
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
