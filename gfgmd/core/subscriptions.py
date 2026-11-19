"""Subscriptions: which of a channel's or playlist's latest uploads are new, and Takeout import."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Iterable

from gfgmd.core.sources import Source

# Items with these availability values can never download without access the user doesn't have.
_UNREACHABLE = {"private", "needs_auth", "subscriber_only", "premium_only"}


@dataclass(frozen=True)
class CheckResult:
    """A check's outcome: uploads to queue, scheduled streams to wait for, and items to ignore."""

    new: list[dict[str, Any]]
    upcoming: list[dict[str, Any]]
    unreachable: list[dict[str, Any]]


def check_urls(source: Source, url: str) -> list[str]:
    """The pages a check reads: a YouTube channel's Videos, Shorts, and Live tabs, else the link itself."""
    if source.kind == "channel" and not source.tab:
        base = f"https://www.youtube.com/{source.source_id}"
        return [f"{base}/videos", f"{base}/shorts", f"{base}/streams"]
    return [url]


def sort_entries(entries: Iterable[dict[str, Any]], archived: set[str], seen: dict[str, str]) -> CheckResult:
    """Split listed entries into new uploads, upcoming streams, and unreachable items.

    Entries already in the archive (downloaded) or already seen (queued, skipped) are dropped, so a
    check never queues the same video twice.
    """
    new: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    unreachable: list[dict[str, Any]] = []
    picked: set[str] = set()
    for entry in entries:
        video_id = str(entry.get("id") or "")
        if not video_id or video_id in archived or video_id in seen or video_id in picked:
            continue
        picked.add(video_id)
        if entry.get("live_status") in ("is_upcoming", "is_live"):
            upcoming.append(entry)
        elif entry.get("availability") in _UNREACHABLE:
            unreachable.append(entry)
        else:
            new.append(entry)
    return CheckResult(new, upcoming, unreachable)


def parse_takeout(text: str) -> list[tuple[str, str]]:
    """(channel link, title) pairs from YouTube Takeout's subscriptions.csv."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows = list(reader)
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    try:
        url_col = next(i for i, name in enumerate(header) if "url" in name)
        title_col = next(i for i, name in enumerate(header) if "title" in name)
    except StopIteration as exc:
        raise ValueError("This isn't a YouTube Takeout subscriptions.csv") from exc
    pairs: list[tuple[str, str]] = []
    for row in rows[1:]:
        if len(row) > max(url_col, title_col):
            url = row[url_col].strip().replace("http://", "https://", 1)
            if url.startswith("https://www.youtube.com/"):
                pairs.append((url, row[title_col].strip()))
    return pairs
