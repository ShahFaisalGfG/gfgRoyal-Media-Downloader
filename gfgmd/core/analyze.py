"""Read a link's details before downloading: title, qualities, subtitles, and a playlist's entries."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from gfgmd.core.command import Auth, analyze_command, list_command, run_marker
from gfgmd.core.errors import Failure, classify
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import is_container, parse_line, pick_thumbnail, title_from_url
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet

# A channel with tens of thousands of uploads still fits; the JSON is one line on stdout.
MAX_JSON_BYTES = 256 * 1024 * 1024


class AnalyzeError(Exception):
    """The link couldn't be read; `failure` says why and what the user can do."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.category.message)
        self.failure = failure


@dataclass(frozen=True)
class Entry:
    """One video in a playlist or channel."""

    id: str
    title: str
    index: int
    duration: float = 0.0
    url: str = ""
    live_status: str = ""
    availability: str = ""
    thumbnail: str = ""


@dataclass(frozen=True)
class Chapter:
    """One chapter of a video, as its creator marked it: its title and where it starts and ends."""

    title: str
    start: float
    end: float


@dataclass(frozen=True)
class AudioTrack:
    """One audio language a video offers; sites such as YouTube add dubbed tracks to the original."""

    code: str
    label: str
    original: bool = False


@dataclass
class Analysis:
    """What a link holds."""

    kind: str  # video or playlist
    title: str
    extractor: str
    webpage_url: str
    uploader: str = ""
    thumbnail: str = ""
    duration: float = 0.0
    live_status: str = ""
    release_timestamp: float = 0.0
    heights: list[int] = field(default_factory=list)
    subtitle_langs: list[str] = field(default_factory=list)
    auto_subtitle_langs: list[str] = field(default_factory=list)
    # The video's own language, and its audio tracks with the original first.
    language: str = ""
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    # Music details when the site knows them (YouTube Music, SoundCloud, Bandcamp).
    artist: str = ""
    track: str = ""
    album: str = ""
    entries: list[Entry] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    # False when entries are themselves lists (a channel's tabs), which can't be picked one by one.
    selectable: bool = True
    size_estimate: int = 0

    @property
    def is_live(self) -> bool:
        """True for a live or scheduled stream."""
        return self.live_status in ("is_live", "is_upcoming")


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def parse_info(info: dict[str, Any], options: DownloadOptions | None = None) -> Analysis:
    """Turn yt-dlp's JSON into an Analysis."""
    playlist = info.get("_type") in ("playlist", "multi_video") or "entries" in info
    result = Analysis(
        kind="playlist" if playlist else "video",
        title=str(info.get("title") or info.get("id") or "Untitled"),
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
        webpage_url=str(info.get("webpage_url") or info.get("original_url") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or info.get("playlist_uploader") or ""),
        thumbnail=pick_thumbnail(info),
        duration=_number(info.get("duration")),
        live_status=str(info.get("live_status") or ""),
        release_timestamp=_number(info.get("release_timestamp")),
    )
    if playlist:
        entries = [entry for entry in info.get("entries") or [] if isinstance(entry, dict)]
        result.selectable = not any(is_container(entry) for entry in entries)
        result.entries = [entry for entry in (entry_from(data, position) for position, data in enumerate(entries, start=1))
                          if entry is not None]
        return result
    formats = [fmt for fmt in info.get("formats") or [] if isinstance(fmt, dict)]
    heights = set()
    for fmt in formats:
        width, height = fmt.get("width"), fmt.get("height")
        if fmt.get("vcodec") not in (None, "none") and isinstance(height, int) and height > 0:
            heights.add(min(height, width) if isinstance(width, int) and width > 0 else height)
    result.heights = sorted(heights, reverse=True)
    result.audio_tracks = audio_tracks(formats)
    original = next((track.code for track in result.audio_tracks if track.original), "")
    result.language = str(info.get("language") or original or "")
    result.artist = str(info.get("artist") or info.get("creator") or "")
    result.track = str(info.get("track") or "")
    result.album = str(info.get("album") or "")
    result.subtitle_langs = sorted(str(key) for key in (info.get("subtitles") or {}) if key != "live_chat")
    result.auto_subtitle_langs = sorted(str(key) for key in (info.get("automatic_captions") or {}))
    result.size_estimate = estimate_size(formats, options or DownloadOptions())
    result.chapters = chapters_of(info)
    return result


def chapters_of(info: dict[str, Any]) -> list[Chapter]:
    """The video's chapters in order; ones without a title or a time are left out."""
    chapters = []
    for item in info.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start_time"), item.get("end_time")
        title = str(item.get("title") or "").strip()
        if title and isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            chapters.append(Chapter(title, float(start), float(end)))
    return chapters


def entry_from(entry: dict[str, Any], position: int) -> Entry | None:
    """One listed video as an Entry (`position` is its place when yt-dlp doesn't number it); None without an ID."""
    if not entry.get("id"):
        return None
    return Entry(
        id=str(entry["id"]),
        title=str(entry.get("title") or title_from_url(str(entry.get("url") or "")) or "Untitled"),
        index=int(entry.get("playlist_index") or position),
        duration=_number(entry.get("duration")),
        url=str(entry.get("url") or entry.get("webpage_url") or ""),
        live_status=str(entry.get("live_status") or ""),
        availability=str(entry.get("availability") or ""),
        thumbnail=pick_thumbnail(entry),
    )


# yt-dlp ranks the original audio track of a YouTube video at this language preference or higher.
_ORIGINAL_PREFERENCE = 10


def audio_tracks(formats: list[dict[str, Any]]) -> list[AudioTrack]:
    """The audio languages among the formats, original first; empty when the site names no languages."""
    found: dict[str, AudioTrack] = {}
    for fmt in formats:
        code = fmt.get("language")
        # Only audio-only formats are tracks; a combined video-and-audio format (YouTube's 360p "18")
        # also carries a language but isn't a dub.
        if not isinstance(code, str) or not code or fmt.get("acodec") in (None, "none") or fmt.get("vcodec") != "none":
            continue
        note = str(fmt.get("format_note") or "")
        preference = fmt.get("language_preference")
        original = "original" in note.lower() or (isinstance(preference, int) and preference >= _ORIGINAL_PREFERENCE)
        label = note.split(",")[0].replace("original", "").replace("(default)", "").strip() or code
        known = found.get(code)
        if known is None or (original and not known.original):
            found[code] = AudioTrack(code, label, original)
    if len(found) < 2:
        return []  # one language: nothing to choose
    return sorted(found.values(), key=lambda track: (not track.original, track.label.casefold()))


def estimate_size(formats: list[dict[str, Any]], options: DownloadOptions) -> int:
    """Roughly how many bytes the chosen quality takes: the best fitting video plus the best audio."""
    def size(fmt: dict[str, Any]) -> int:
        return int(_number(fmt.get("filesize")) or _number(fmt.get("filesize_approx")))
    audio = [size(fmt) for fmt in formats if fmt.get("vcodec") == "none" and fmt.get("acodec") not in (None, "none")]
    best_audio = max(audio, default=0)
    if options.kind == "audio":
        return best_audio
    cap = options.max_height or 100_000
    videos = [fmt for fmt in formats if fmt.get("vcodec") not in (None, "none") and isinstance(fmt.get("height"), int)]
    fitting = [fmt for fmt in videos if min(int(fmt["height"]), int(fmt.get("width") or fmt["height"])) <= cap]
    if not fitting:
        return best_audio
    best_height = max(min(int(fmt["height"]), int(fmt.get("width") or fmt["height"])) for fmt in fitting)
    top = [size(fmt) for fmt in fitting if min(int(fmt["height"]), int(fmt.get("width") or fmt["height"])) == best_height]
    return max(top, default=0) + best_audio


def items_spec(indices: Iterable[int]) -> str:
    """A --playlist-items value for the chosen positions: [1,2,3,5] -> "1:3,5"."""
    ordered = sorted(set(index for index in indices if index > 0))
    parts: list[str] = []
    start = previous = None
    for index in ordered:
        if start is None:
            start = previous = index
        elif previous is not None and index == previous + 1:
            previous = index
        else:
            parts.append(f"{start}:{previous}" if start != previous else str(start))
            start = previous = index
    if start is not None:
        parts.append(f"{start}:{previous}" if start != previous else str(start))
    return ",".join(parts)


def analyze(url: str, tools: ToolSet, cache_dir: Path, auth: Auth | None = None,
            options: DownloadOptions | None = None, single: bool = False, stop: threading.Event | None = None,
            on_line: Callable[[str], None] | None = None) -> Analysis:
    """Run yt-dlp to read a link; raises AnalyzeError with the reason when it can't."""
    command = analyze_command(url, tools, cache_dir, auth, options, single)
    payload: list[str] = []
    errors: list[str] = []

    def collect(stream: str, line: str) -> None:
        text = line.strip()
        if stream == "out" and text.startswith("{"):
            payload.append(text)
        elif text.startswith("ERROR:"):
            errors.append(text[6:].strip())
        elif on_line is not None and text:
            on_line(text)

    code, stopped = run_to_completion(command, collect, stop, max_line_bytes=MAX_JSON_BYTES)
    if stopped:
        raise AnalyzeError(classify("Cancelled"))
    if payload:
        try:
            info = json.loads(payload[-1])
        except ValueError as error:
            raise AnalyzeError(classify(f"yt-dlp returned unreadable details: {error}")) from error
        if isinstance(info, dict):
            return parse_info(info, options)
    reason = errors[-1] if errors else f"yt-dlp exited with status {code}"
    raise AnalyzeError(classify(reason, signed_in=auth is not None, single=single))


def analyze_list(url: str, tools: ToolSet, cache_dir: Path, auth: Auth | None = None,
                 options: DownloadOptions | None = None, stop: threading.Event | None = None,
                 on_entry: Callable[[dict[str, Any]], None] | None = None,
                 on_line: Callable[[str], None] | None = None) -> Analysis:
    """Read a playlist or channel page by page: each video goes to `on_entry` as it arrives (from the
    worker thread), so a long list shows its first videos in seconds; raises AnalyzeError when the
    list can't be read."""
    marker = run_marker()
    entries: list[dict[str, Any]] = []
    playlist: dict[str, Any] = {}
    errors: list[str] = []

    def collect(stream: str, line: str) -> None:
        event = parse_line(stream, line, marker)
        if event.kind == "entry":
            entries.append(event.data)
            if on_entry is not None:
                on_entry(event.data)
        elif event.kind == "pl":
            playlist.update(event.data)
        elif event.kind == "error":
            errors.append(event.text)
        elif on_line is not None and event.text:
            on_line(event.text)

    code, stopped = run_to_completion(list_command(url, tools, cache_dir, auth, options, marker), collect, stop)
    if stopped:
        raise AnalyzeError(classify("Cancelled"))
    if code != 0 and not entries:
        reason = errors[-1] if errors else f"yt-dlp exited with status {code}"
        raise AnalyzeError(classify(reason, signed_in=auth is not None))
    return parse_info({**playlist, "_type": "playlist", "entries": entries}, options)
