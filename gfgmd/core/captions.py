"""Timed text: parse SRT, WebVTT, and LRC files into cues, find the cue at a time, and write LRC.

The players show subtitles and synced lyrics from these cues, and the lyrics step writes LRC files
with them. Stdlib only, so the command-line tool shares it.
"""

from __future__ import annotations

import bisect
import html
import re
from dataclasses import dataclass
from pathlib import Path

from gfgmd.core.naming import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS

# Caption and lyric files are small; anything larger isn't one.
MAX_CAPTION_BYTES = 4 * 1024 * 1024
CAPTION_EXTENSIONS = (".srt", ".vtt", ".lrc")
# A cover saved beside its song ("Song.jpg"), as WAV files get, since they can't hold one.
COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# How long the last lyric line (which has no next line to end it) stays current.
_LAST_LINE_SECONDS = 6.0

_TIMING = re.compile(
    r"(?P<start>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*(?P<end>(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})")
_TAG = re.compile(r"<[^>]*>|\{\\[^}]*\}")
_LRC_STAMP = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_LRC_WORD = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_LRC_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\]", re.IGNORECASE)
_LRC_TAG = re.compile(r"^\[[A-Za-z#]+:.*\]$")


@dataclass(frozen=True)
class Cue:
    """One caption or lyric line shown from `start` to `end` seconds."""

    start: float
    end: float
    text: str


def clock(value: str) -> float:
    """Seconds from "1:02:03.456", "02:03,456", or "2:03.4"."""
    parts = value.replace(",", ".").split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def _clean(text: str) -> str:
    """Caption text without markup, entities, or extra spaces."""
    return re.sub(r"[ \t]+", " ", html.unescape(_TAG.sub("", text))).strip()


def parse_timed_blocks(text: str) -> list[Cue]:
    """SRT or WebVTT cues: a "start --> end" line followed by text lines, blocks split by blank lines.

    Rolling auto-captions repeat the previous line at the top of each block; a block whose first
    line is the last shown line keeps only what is new.
    """
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "")):
        lines = block.splitlines()
        for position, line in enumerate(lines):
            match = _TIMING.search(line)
            if match is None:
                continue
            body = [_clean(entry) for entry in lines[position + 1:]]
            body = [entry for entry in body if entry]
            if cues and body and body[0] == cues[-1].text.splitlines()[-1] and len(body) > 1:
                body = body[1:]
            words = "\n".join(body)
            if words and not (cues and cues[-1].text == words):
                cues.append(Cue(clock(match["start"]), clock(match["end"]), words))
            break
    return sorted(cues, key=lambda cue: cue.start)


def parse_lrc(text: str) -> list[Cue]:
    """LRC lyric lines; a line may carry several time stamps, and word timings are dropped."""
    offset = 0.0
    timed: list[tuple[float, str]] = []
    for raw in text.replace("﻿", "").splitlines():
        line = raw.strip()
        found = _LRC_OFFSET.match(line)
        if found:
            offset = int(found.group(1)) / 1000.0
            continue
        stamps = []
        while True:
            match = _LRC_STAMP.match(line)
            if match is None:
                break
            stamps.append(int(match.group(1)) * 60 + float(match.group(2).replace(":", ".")))
            line = line[match.end():]
        if not stamps:
            continue  # metadata such as [ar:Artist], or an untimed line
        words = _clean(_LRC_WORD.sub("", line))
        timed.extend((max(0.0, stamp - offset), words) for stamp in stamps)
    timed.sort(key=lambda entry: entry[0])
    cues = []
    for position, (start, words) in enumerate(timed):
        end = timed[position + 1][0] if position + 1 < len(timed) else start + _LAST_LINE_SECONDS
        cues.append(Cue(start, end, words))
    return cues


def is_synced_lrc(text: str) -> bool:
    """True when the text has at least one timed lyric line."""
    return any(_LRC_STAMP.match(line.strip()) for line in text.splitlines())


def parse_file(path: Path) -> list[Cue]:
    """The cues in an SRT, VTT, or LRC file; empty when it's missing, too large, or unreadable."""
    try:
        if path.stat().st_size > MAX_CAPTION_BYTES:
            return []
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    if path.suffix.lower() == ".lrc":
        return parse_lrc(text)
    return parse_timed_blocks(text)


def cue_at(cues: list[Cue], seconds: float) -> int:
    """The index of the cue showing at `seconds`, or -1 between cues."""
    index = bisect.bisect_right([cue.start for cue in cues], seconds) - 1
    return index if index >= 0 and seconds < cues[index].end else -1


def line_at(cues: list[Cue], seconds: float) -> int:
    """The lyric line reached at `seconds` (it stays current until the next one), or -1 before the first."""
    return bisect.bisect_right([cue.start for cue in cues], seconds) - 1


def _stamp(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"[{int(minutes):02d}:{rest:05.2f}]"


def to_lrc(cues: list[Cue], title: str = "", artist: str = "", album: str = "", length: float = 0.0) -> str:
    """An LRC document: ID tags, then one timed line per cue (multi-line cues joined with " / ")."""
    lines = []
    for tag, value in (("ti", title), ("ar", artist), ("al", album)):
        if value:
            lines.append(f"[{tag}:{value.replace('[', '(').replace(']', ')')}]")
    if length > 0:
        minutes, rest = divmod(int(length), 60)
        lines.append(f"[length:{minutes:02d}:{rest:02d}]")
    lines += [f"{_stamp(cue.start)}{cue.text.replace(chr(10), ' / ')}" for cue in cues]
    return "\n".join(lines) + "\n"


def plain_text(cues: list[Cue]) -> str:
    """The cue text as plain lines, for an unsynced lyrics tag."""
    return "\n".join(cue.text for cue in cues if cue.text)


def sidecars(media: Path) -> list[Path]:
    """Caption and lyric files saved beside `media` ("Song.lrc", "Video.en.srt"), sorted by name.

    "Song.Remix.lrc" belongs to "Song.Remix.mp3" when that file is there, not to "Song.mp3".
    """
    stem = media.stem
    try:
        entries = list(media.parent.iterdir())
    except OSError:
        return []
    others = {entry.stem for entry in entries
              if entry.suffix[1:].lower() in MEDIA_EXTENSIONS and entry.stem != stem}
    found = [entry for entry in entries
             if entry.is_file() and entry.suffix.lower() in CAPTION_EXTENSIONS
             and (entry.stem == stem or (entry.stem.startswith(stem + ".") and entry.stem not in others))]
    return sorted(found, key=lambda entry: (entry.stem != stem, entry.name.casefold()))


def companion_files(media: Path) -> list[Path]:
    """The caption, lyric, and cover files beside `media` that belong to it (removed along with it).

    A saved picture has none: another picture of the same name beside it is a picture of its own.
    """
    if media.suffix[1:].lower() in IMAGE_EXTENSIONS:
        return []
    covers = [media.with_suffix(extension) for extension in COVER_EXTENSIONS]
    return sidecars(media) + [cover for cover in covers if cover.is_file()]
