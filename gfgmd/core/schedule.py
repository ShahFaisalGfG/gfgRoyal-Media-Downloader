"""Time rules: speed limits by time of day, the queue's start time, check intervals, and live waits."""

from __future__ import annotations

import random
from datetime import datetime, time as clock, timedelta
from typing import Any, Iterable

# A scheduled stream is started this long before its announced time; yt-dlp then waits for it.
LIVE_LEAD_SECONDS = 300
CHECK_JITTER = 0.10


def _parse_clock(text: str) -> clock:
    hours, minutes = (int(part) for part in text.split(":"))
    return clock(hours, minutes)


def in_window(moment: datetime, start: str, end: str) -> bool:
    """True when moment's time of day is in [start, end); a window may cross midnight."""
    now, begin, finish = moment.time(), _parse_clock(start), _parse_clock(end)
    if begin < finish:
        return begin <= now < finish
    return now >= begin or now < finish


def limit_at(moment: datetime, base_kib: int, windows: Iterable[dict[str, Any]]) -> int:
    """The total speed limit in KiB/s at a moment: the lowest of the base limit and active windows (0 = none)."""
    limits = [base_kib] if base_kib > 0 else []
    for window in windows:
        if in_window(moment, window["start"], window["end"]):
            limits.append(int(window["limit_kib"]))
    return min(limits) if limits else 0


def per_job_limit(total_kib: int, active_jobs: int) -> int:
    """Bytes per second for each running download when a total limit is shared (0 = none)."""
    if total_kib <= 0:
        return 0
    return max(total_kib * 1024 // max(active_jobs, 1), 16 * 1024)


def next_queue_start(now: datetime, start: str) -> datetime:
    """The next time the queue may start at "HH:MM" (today if still ahead, else tomorrow)."""
    begin = datetime.combine(now.date(), _parse_clock(start), tzinfo=now.tzinfo)
    return begin if begin > now else begin + timedelta(days=1)


def next_check(now: float, interval_hours: int, rng: random.Random | None = None) -> float:
    """When a subscription is checked next: the interval with up to 10% jitter, so checks spread out."""
    seconds = interval_hours * 3600
    jitter = (rng or random).uniform(-CHECK_JITTER, CHECK_JITTER) * seconds
    return now + seconds + jitter


def stagger(due: int, start: float, gap: float = 10.0) -> list[float]:
    """Start times for overdue checks after a long time off, `gap` seconds apart."""
    return [start + index * gap for index in range(due)]


def live_launch_time(release_timestamp: float, now: float) -> float:
    """When to start a scheduled stream's job: shortly before its announced start, never in the past."""
    return max(release_timestamp - LIVE_LEAD_SECONDS, now)
