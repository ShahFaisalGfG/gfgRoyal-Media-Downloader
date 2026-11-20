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


def media_noun(kind: str, count: int = 1) -> str:
    """What to call downloaded media: "song" for audio, "video" otherwise, plural unless count is 1."""
    noun = "song" if kind == "audio" else "video"
    return noun if count == 1 else noun + "s"


def count_media(count: int, kind: str) -> str:
    """A count of songs or videos: (1, "audio") -> "1 song", (8, "video") -> "8 videos"."""
    return f"{count} {media_noun(kind, count)}"


def about_time(seconds: float) -> str:
    """A rough length in words: "a few seconds", "about 40 seconds", "about 3 minutes", "about 1 hour 20 minutes".

    Plain words instead of "1:15", which reads as either minutes or hours.
    """
    total = int(max(seconds, 0))
    if total < 10:
        return "a few seconds"
    if total < 60:
        return f"about {round(total / 10) * 10} seconds"
    if total < 3600:
        minutes = max(1, round(total / 60))
        if minutes == 60:
            return "about 1 hour"
        return f"about {minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(total, 3600)
    minutes = round(rest / 300) * 5  # to the nearest 5 minutes
    if minutes == 60:
        hours, minutes = hours + 1, 0
    text = f"about {hours} hour{'s' if hours != 1 else ''}"
    if minutes and hours < 10:
        text += f" {minutes} minutes"
    return text


def format_time_left(seconds: float) -> str:
    """How long a download has left: "about 3 minutes left"."""
    return f"{about_time(seconds)} left"


def format_wait(seconds: float) -> str:
    """When something happens next: "in 20 seconds", "in 2 minutes", "in about 1 hour"."""
    total = max(int(seconds), 1)
    if total < 60:
        return f"in {total} second{'s' if total != 1 else ''}"
    if total < 3600:
        minutes = max(1, round(total / 60))
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    return "in " + about_time(total)
