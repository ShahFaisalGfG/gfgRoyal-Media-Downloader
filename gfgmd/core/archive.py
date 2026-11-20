"""Download archives: yt-dlp's record of finished videos, kept per source and per format profile."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from gfgmd.core.locks import FileLock
from gfgmd.core.platform import hide_folder
from gfgmd.core.sources import Source

ARCHIVE_FOLDER = ".archives"


def archive_path(output_root: Path, source: Source, profile: str) -> Path:
    """Keep each playlist's, channel's, and single-video collection's archive separate per profile.

    The original script named them `<key>-<height>p.txt`; video profiles keep that name, so its archives
    still skip what it downloaded.
    """
    return output_root / ARCHIVE_FOLDER / f"{source.archive_key}-{profile}.txt"


def read_archive_ids(archive: Path) -> set[str]:
    """The video IDs recorded in an archive, ignoring a last line cut short by a crash."""
    try:
        data = archive.read_bytes()
    except FileNotFoundError:
        return set()
    text = data.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if not text.endswith("\n"):
        lines = lines[:-1]  # yt-dlp writes whole lines; a line without its newline is unfinished
    ids: set[str] = set()
    for line in lines:
        extractor, separator, video_id = line.strip().partition(" ")
        if extractor and separator and video_id:
            ids.add(video_id)
    return ids


def append_archive(archive: Path, extractor: str, video_ids: Iterable[str]) -> int:
    """Record IDs as already downloaded (subscriptions that start from new uploads only)."""
    known = read_archive_ids(archive)
    lines = [f"{extractor.lower()} {video_id}\n" for video_id in dict.fromkeys(video_ids) if video_id not in known]
    if not lines:
        return 0
    archive.parent.mkdir(parents=True, exist_ok=True)
    hide_folder(archive.parent)
    with archive.open("a", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)
    return len(lines)


class ArchiveLock(FileLock):
    """An exclusive lock on one archive shared by the app and the command-line tool.

    Two yt-dlp runs appending to the same archive could interleave lines, and two runs of the same
    playlist would download the same videos twice; the second run waits for the first instead.
    """


def remove_lock_files(output_root: Path) -> None:
    """Delete stale archive lock files (they hold no state; the OS lock dies with its process)."""
    folder = output_root / ARCHIVE_FOLDER
    if not folder.is_dir():
        return
    for lock in folder.glob("*.lock"):
        try:
            os.remove(lock)
        except OSError:
            pass  # still locked by a running download
