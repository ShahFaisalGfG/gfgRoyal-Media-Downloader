"""Measure which fragment count downloads fastest on this connection (Preferences > Optimize).

Each candidate downloads the same video for a few seconds into a temporary folder; the bytes
received after a short warm-up give its speed. Two rounds in opposite orders even out a connection
that speeds up or slows down while testing. The default is kept unless another value is clearly
faster, so a noisy measurement doesn't swap settings back and forth.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from gfgmd.core.command import RunPaths, download_command
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import ProgressTracker
from gfgmd.core.runner import ProcessRunner
from gfgmd.core.sources import source_from_url
from gfgmd.core.tools import ToolSet

CANDIDATES = (4, 8, 16)
WARM_UP_S = 2.0


def pick_fastest(speeds: dict[int, float], default: int, margin: float = 0.05) -> int:
    """The fastest value, but the default unless the winner beats it by more than `margin`."""
    if not speeds:
        return default
    best = max(speeds, key=lambda count: speeds[count])
    base = speeds.get(default, 0.0)
    return best if base <= 0 or speeds[best] > base * (1 + margin) else default


def measure_once(url: str, fragments: int, tools: ToolSet, cache: Path, seconds: float,
                 stop: threading.Event) -> float:
    """Bytes per second for one fragment count, measured after the warm-up."""
    folder = Path(tempfile.mkdtemp(prefix="gfgmd-speed-"))
    try:
        options = DownloadOptions(fragments=fragments).validate()
        paths = RunPaths(folder, folder / "archive.txt", folder / "job", cache)
        command = download_command(url, source_from_url(url), options, tools, paths)
        tracker = ProgressTracker()
        runner = ProcessRunner(command, tracker.feed)
        runner.start()
        started = time.monotonic()
        warm_bytes, warm_time = 0, 0.0
        while time.monotonic() - started < WARM_UP_S + seconds and not stop.is_set():
            time.sleep(0.25)
            if not warm_time and time.monotonic() - started >= WARM_UP_S:
                warm_bytes, warm_time = tracker.snapshot().downloaded, time.monotonic()
        end_bytes, end_time = tracker.snapshot().downloaded, time.monotonic()
        runner.stop()
        runner.wait()
        if not warm_time or end_time <= warm_time:
            return 0.0
        return max(end_bytes - warm_bytes, 0) / (end_time - warm_time)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def measure(url: str, tools: ToolSet, cache: Path, stop: threading.Event, seconds: float = 6.0,
            progress: Callable[[int, int], None] | None = None,
            candidates: tuple[int, ...] = CANDIDATES) -> dict[int, float]:
    """Average speed per fragment count over two rounds in opposite orders."""
    totals: dict[int, list[float]] = {count: [] for count in candidates}
    plan = list(candidates) + list(reversed(candidates))
    for step, count in enumerate(plan, start=1):
        if stop.is_set():
            break
        totals[count].append(measure_once(url, count, tools, cache, seconds, stop))
        if progress is not None:
            progress(step, len(plan))
    return {count: sum(values) / len(values) for count, values in totals.items() if values}
