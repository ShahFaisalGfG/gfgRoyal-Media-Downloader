# format.py - human-readable sizes, speeds, and durations (stdlib only)

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_bytes(size: float) -> str:
    """A byte count in binary units with one decimal above KB: 1536 -> "1.5 KB"."""
    value = float(max(size, 0))
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_duration(seconds: float) -> str:
    """Seconds as m:ss or h:mm:ss: 75 -> "1:15", 3725 -> "1:02:05"."""
    total = int(max(seconds, 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
