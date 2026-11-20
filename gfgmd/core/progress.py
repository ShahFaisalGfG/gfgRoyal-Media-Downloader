"""Turn yt-dlp's output lines into events, and events into one job's progress snapshot.

The command builder asks yt-dlp to print machine-readable lines that start with "@@gfgr:" followed
by a kind and a JSON object (see command.py). Everything else is a plain log line; "ERROR:" and
"WARNING:" lines are kept for the error classifier.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

MARKER = "@@gfgr:"
_BARE_NA = re.compile(r"(?<=[:\[,])\s*NA\s*(?=[,}\]])")
_ITEM_PREFIX = re.compile(r"^\[(?P<extractor>[^\]]+)\] (?P<id>[^:\s]{1,128}): ")
_PAGE = re.compile(r"Downloading (?:API JSON )?page (\d+)", re.IGNORECASE)
_WAIT = re.compile(r"\[wait\] Remaining time until next attempt: (\d+):(\d+):(\d+)")
_ITEM_OF = re.compile(r"^\[download\] Downloading item (\d+) of (\d+)")
_ARCHIVED = "has already been recorded in the archive"
# A link whose ID yt-dlp knows without reading the page (YouTube) is skipped as "[download] <id>: has
# already been recorded in the archive"; other skips name the title instead.
_ARCHIVED_ID = re.compile(r"^\[download\] (?P<id>[^\s:]{1,128}): has already been recorded in the archive")

# yt-dlp's playlist file (see command.py), written before the playlist's first video downloads.
_LIST_WRITTEN = re.compile(r"^\[info\] Writing playlist metadata as JSON to: (?P<path>.+)$")
# A download yt-dlp is retrying inside one attempt ("[download] Got error: ... Retrying fragment 1 (2/10)...").
_GOT_ERROR = "[download] Got error:"
# Lines that mean yt-dlp moved on, which the stall check counts as activity; the last is ffmpeg's own
# progress, the only sign of life when yt-dlp hands a download to ffmpeg.
_PROGRESS_LOG = re.compile(r"^\[download\] (?:Downloading item|Destination:|Downloading playlist)|"
                           r"^\[info\] [^:]+: Downloading \d+ format|^(?:frame=\s*\d+|size=\s*\S+).*time=")

# The post-processor that converts audio; its ffmpeg run writes a -progress file (see command.py).
_AUDIO_CONVERSION = "ExtractAudio"
# The step each yt-dlp post-processor stands for, by its name without the "FFmpeg" prefix (yt-dlp
# reports "ThumbnailsConvertor" for FFmpegThumbnailsConvertorPP); anything else is "Finishing up".
_PP_STAGES = {
    "Merger": "Putting the video together",
    "EmbedSubtitle": "Adding subtitles",
    "EmbedThumbnail": "Adding the cover",
    "Metadata": "Adding the title and details",
    "VideoRemuxer": "Preparing the file",
    "VideoConvertor": "Preparing the file",
    "SubtitlesConvertor": "Preparing subtitles",
    "ThumbnailsConvertor": "Preparing the cover",
    "SponsorBlock": "Checking for sponsor parts",
    "ModifyChapters": "Handling sponsor parts",
}
FINISHING = "Finishing up"
# Snapshot phases: what the current video is doing, which decides how its progress reads.
PHASE_DOWNLOAD, PHASE_POST, PHASE_WAIT = "download", "post", "wait"


def stage_of(postprocessor: str, convert_label: str = "") -> str:
    """The step a yt-dlp post-processor name stands for, in plain words."""
    name = postprocessor[6:] if postprocessor.startswith("FFmpeg") else postprocessor
    if name == _AUDIO_CONVERSION:
        return f"Converting to {convert_label}" if convert_label else "Converting the sound"
    return _PP_STAGES.get(name, FINISHING)


@dataclass(frozen=True)
class Event:
    """One parsed output line."""

    kind: str  # dl, pp, item, parts, file, entry, pl, error, warning, log
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    stream: str = "out"


def _loads(payload: str) -> Any:
    try:
        return json.loads(payload)
    except ValueError:
        try:
            return json.loads(_BARE_NA.sub("null", payload))
        except ValueError:
            return None


def parse_line(stream: str, line: str, marker: str = MARKER) -> Event:
    """Classify one output line; only lines starting with this run's `marker` are the app's own."""
    text = line.strip()
    if text.startswith(marker):
        kind, _, payload = text[len(marker):].partition(" ")
        value = _loads(payload)
        if kind == "parts":
            data = {"parts": value if isinstance(value, list) else []}
        elif isinstance(value, dict):
            data = value
        else:
            data = {}
        return Event(kind, data, text, stream)
    if text.startswith("ERROR:"):
        return Event("error", _item_of(text[6:].strip()), text[6:].strip(), stream)
    if text.startswith("WARNING:"):
        return Event("warning", _item_of(text[8:].strip()), text[8:].strip(), stream)
    return Event("log", {}, text, stream)


def _item_of(message: str) -> dict[str, Any]:
    """The extractor and item ID an error names ("[youtube] abc123: Private video")."""
    match = _ITEM_PREFIX.match(message)
    if match is None:
        return {}
    return {"extractor": match.group("extractor"), "id": match.group("id")}


def read_convert_progress(path: Path, since: float) -> tuple[float, float] | None:
    """(seconds converted, speed as a multiple of real time) from ffmpeg's -progress file.

    None when the file is missing or older than `since` (the previous item's conversion).
    """
    try:
        if path.stat().st_mtime < since - 1:
            return None
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 4096))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    seconds, speed = None, 0.0
    for line in tail.splitlines():
        key, _, value = line.strip().partition("=")
        if key in ("out_time_us", "out_time_ms") and value.isdigit():
            seconds = int(value) / 1_000_000  # both keys count microseconds
        elif key == "speed" and value.endswith("x"):
            try:
                speed = float(value[:-1])
            except ValueError:
                speed = 0.0
    return (seconds, speed) if seconds is not None else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def pick_thumbnail(info: dict[str, Any]) -> str:
    """A medium-size thumbnail URL (about 320 pixels wide when the site lists sizes)."""
    thumbs = [thumb for thumb in info.get("thumbnails") or [] if isinstance(thumb, dict) and thumb.get("url")]
    sized = [thumb for thumb in thumbs if isinstance(thumb.get("width"), int)]
    if sized:
        return str(min(sized, key=lambda thumb: abs(int(thumb["width"]) - 320))["url"])
    if thumbs:
        return str(thumbs[-1]["url"])
    return str(info.get("thumbnail") or "")


# Link path parts that name a page type, never a video ("watch" in youtube.com/watch?v=...).
_PATH_WORDS = {"watch", "video", "videos", "embed", "status", "shorts", "reel", "reels", "p", "tv", "details",
               "play", "track", "tracks", "clip", "clips", "media", "item", "v", "w", "post", "posts", "view"}


def title_from_url(url: str) -> str:
    """A readable title from a link's last part when a list names no title ("world-on-fire-1" ->
    "World on fire 1"); "" when that part is only an ID or a number."""
    last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] if url else ""
    if last.lower() in _PATH_WORDS:
        return ""
    words = re.sub(r"[-_+.]+", " ", unquote(last)).strip()
    if not re.search(r"[^\W\d_]{3}", words) or (" " not in words and len(words) >= 10 and re.search(r"\d", words)):
        return ""  # an ID such as "dQw4w9WgXcQ" or "75206121"
    return words[:1].upper() + words[1:]


def is_container(entry: dict[str, Any]) -> bool:
    """True for an entry that is itself a list (a channel's Videos or Shorts tab), not one video."""
    return entry.get("_type") == "playlist" or str(entry.get("ie_key") or "").endswith("Tab")


def listed_entries(info: dict[str, Any], offset: int = 0) -> list[dict[str, Any]]:
    """The videos a playlist file lists, in order: id, title, index, duration, url, and thumbnail.

    Lists inside it (a channel's tabs) are left out; yt-dlp writes each of those as a file of its own
    when it reaches it, numbered after the videos listed before (`offset`). With --playlist-items,
    `requested_entries` holds each listed video's place in the whole playlist.
    """
    entries = info.get("entries")
    if not isinstance(entries, list):
        return []
    places = info.get("requested_entries")
    places = places if isinstance(places, list) and len(places) == len(entries) else None
    listed = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or is_container(entry) or not entry.get("id"):
            continue
        place = places[position] if places is not None else position + 1
        index = offset + (place if isinstance(place, int) else position + 1)
        listed.append({
            "id": str(entry["id"]),
            "title": str(entry.get("title") or title_from_url(str(entry.get("url") or ""))),
            "index": index,
            "duration": _number(entry.get("duration")) or 0.0,
            "url": str(entry.get("webpage_url") or entry.get("url") or ""),
            "thumbnail": pick_thumbnail(entry),
        })
    return listed


# Totals under this are yt-dlp's guess from the first small part of a download ("1.0 KB of 1.0 KB").
FIRST_GUESS_BYTES = 64 * 1024


@dataclass
class Snapshot:
    """What the UI shows for a running job; plain values so it can cross threads."""

    stage: str = "Starting"
    title: str = ""
    playlist_title: str = ""
    thumbnail: str = ""
    item_id: str = ""
    item_index: int = 0
    item_count: int = 0
    items_done: int = 0
    # Items yt-dlp skipped because the archive says they were downloaded before.
    archived: int = 0
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: int = -1
    fragment: str = ""
    item_fraction: float = 0.0
    overall: float = 0.0
    is_live: bool = False
    page: int = 0
    wait_seconds: int = -1
    updated: float = 0.0
    # The current item's length in seconds, and how much of its audio conversion is done (-1: unknown).
    duration: float = 0.0
    convert_fraction: float = -1.0
    # PHASE_DOWNLOAD while the current video downloads (or connects), PHASE_POST while it is converted
    # or put together, PHASE_WAIT while waiting (to try again, for a stream, for another download).
    phase: str = ""

    @property
    def size_guessed(self) -> bool:
        """True while the total is yt-dlp's opening guess from one small part; the next line has the full size."""
        return 0 < self.total < FIRST_GUESS_BYTES

    def as_dict(self) -> dict[str, Any]:
        """The snapshot as a dict (for the database and QML)."""
        return dict(self.__dict__)


class ProgressTracker:
    """Fold a job's events into a snapshot; thread-safe so readers feed while the UI polls.

    Besides the snapshot it keeps, for the queue, the videos a playlist lists (from yt-dlp's
    playlist file) and how each one went, handed over by take_updates(); and when the download last
    moved, so a stalled video can be noticed (stalled()).
    """

    def __init__(self, expected_items: int = 0, convert_label: str = "", marker: str = MARKER) -> None:
        self._lock = threading.Lock()
        # The start of the lines the app asked yt-dlp to print in this run (see command.run_marker).
        self._marker = marker
        self._snap = Snapshot(item_count=expected_items)
        self._expected = expected_items
        # The audio format a conversion makes ("MP3"), for "Converting to MP3".
        self._convert_label = convert_label
        self._parts: dict[str, int] = {}  # format_id -> expected bytes for the current item
        self._done_parts: dict[str, int] = {}  # format_id -> bytes of parts already finished
        self._seen_items: set[str] = set()
        self.files: list[dict[str, Any]] = []
        self.errors: list[Event] = []
        self.warnings: list[Event] = []
        self.entries: list[dict[str, Any]] = []
        self.playlist: dict[str, Any] = {}
        # Partial files yt-dlp reported writing, so a cancelled download can remove them.
        self.partials: set[str] = set()
        # IDs of the videos the archive skipped, when yt-dlp named them.
        self.archived_ids: list[str] = []
        # When the current audio conversion started (wall clock; 0 when none is running).
        self.converting_since = 0.0
        # When the download last moved on (monotonic), for stalled().
        self.last_activity = time.monotonic()
        self._last_bytes = (-1, -1)  # (downloaded bytes, fragment index) of the latest progress line
        # A playlist file yt-dlp announced, and the same once its next line shows the file is written.
        self._pending_list = ""
        self._list_file = ""
        self._updates: list[tuple[str, Any]] = []
        # The stream of an "ERROR:" line yt-dlp ended with a carriage return; its text is the next line.
        self._blank_error = ""

    def feed(self, stream: str, line: str) -> Event:
        """Parse a line, update the snapshot, and return the event."""
        event = parse_line(stream, line, self._marker)
        with self._lock:
            if self._pending_list and stream == "out":
                # yt-dlp writes the file between announcing it and its next line on the same stream.
                self._list_file, self._pending_list = self._pending_list, ""
            self._apply(event)
            self._snap.updated = time.monotonic()
        return event

    def pop_list_file(self) -> str:
        """The playlist file yt-dlp has just written, once ("" when there is none new)."""
        with self._lock:
            path, self._list_file = self._list_file, ""
        return path

    def snapshot(self) -> Snapshot:
        """A copy of the current snapshot."""
        with self._lock:
            return Snapshot(**self._snap.__dict__)

    def mark_stage(self, stage: str, phase: str = "") -> None:
        """Set the stage from outside (Trying again in 20 seconds); a wait clears the last video's sizes."""
        with self._lock:
            snap = self._snap
            snap.stage = stage
            if phase:
                snap.phase = phase
            if phase == PHASE_WAIT:
                snap.downloaded, snap.total, snap.speed, snap.eta, snap.fragment = 0, 0, 0.0, -1, ""

    def take_updates(self) -> list[tuple[str, Any]]:
        """What happened to the playlist's videos since the last call.

        ("state", (id, "archived", "")) when the archive skipped a video downloaded before, or
        ("archived_at", position) when it named the video by title, not ID (the executor knows which
        video is at that place in the list). Failures and the list itself are the executor's.
        """
        with self._lock:
            updates, self._updates = self._updates, []
        return updates

    def stalled(self, seconds: float) -> str:
        """The video that has been downloading without moving for `seconds`, or "".

        Only the download counts: a merge or conversion can run long with nothing to report, and a
        live recording or a wait for a stream is meant to sit still.
        """
        with self._lock:
            snap = self._snap
            if snap.phase != PHASE_DOWNLOAD or snap.is_live or not snap.item_id:
                return ""
            return snap.item_id if time.monotonic() - self.last_activity > seconds else ""

    def _moved(self) -> None:
        self.last_activity = time.monotonic()

    def _apply(self, event: Event) -> None:
        snap = self._snap
        data = event.data
        if event.kind == "item":
            item_id = str(data.get("id") or "")
            if item_id and item_id not in self._seen_items:
                self._seen_items.add(item_id)
                snap.item_index = max(snap.item_index, len(self._seen_items))
            snap.item_id = item_id
            snap.title = str(data.get("title") or snap.title)
            if item_id and data.get("title"):
                self._updates.append(("titled", (item_id, str(data["title"]))))
            snap.playlist_title = str(data.get("playlist_title") or snap.playlist_title)
            snap.thumbnail = str(data.get("thumbnail") or snap.thumbnail)
            count = data.get("n_entries")
            if isinstance(count, int) and count > 0 and not self._expected:
                snap.item_count = count
            snap.is_live = data.get("live_status") == "is_live"
            snap.stage = "Recording" if snap.is_live else "Starting"
            snap.phase = PHASE_DOWNLOAD
            snap.duration = _number(data.get("duration")) or 0.0
            self.converting_since = 0.0
            snap.item_fraction = 0.0
            snap.downloaded = 0
            snap.total = 0
            snap.speed, snap.eta, snap.fragment = 0.0, -1, ""
            self._parts = {}
            self._done_parts = {}
            self._last_bytes = (-1, -1)
            self._moved()
        elif event.kind == "parts":
            self._parts = {}
            for part in data.get("parts", []):
                if isinstance(part, dict):
                    size = _number(part.get("filesize")) or _number(part.get("filesize_approx")) or 0
                    self._parts[str(part.get("format_id"))] = int(size)
        elif event.kind == "dl":
            self._apply_download(data)
        elif event.kind == "pp":
            progress = data.get("p") if isinstance(data.get("p"), dict) else {}
            name = str((progress or {}).get("postprocessor") or "")
            self._moved()
            if (progress or {}).get("status") == "started":
                snap.stage = stage_of(name, self._convert_label)
                # Steps before the download (preparing the cover) leave it in the download phase.
                if self._done_parts:
                    snap.phase = PHASE_POST
                # The download's speed and time left no longer apply.
                snap.speed, snap.eta = 0.0, -1
                plain = name[6:] if name.startswith("FFmpeg") else name
                self.converting_since = time.time() if plain == _AUDIO_CONVERSION else 0.0
        elif event.kind == "file":
            self.converting_since = 0.0
            self.files.append(data)
            snap.items_done += 1
            snap.item_fraction = 1.0
            snap.stage = "Saved"
            snap.phase = ""
            self._moved()
        elif event.kind == "entry":
            self.entries.append(data)
        elif event.kind == "pl":
            self.playlist = data
        elif event.kind == "error":
            if event.text:
                self.errors.append(event)
                snap.phase = ""  # the video gave up; what comes next is the next one
            else:
                self._blank_error = event.stream
        elif event.kind == "warning":
            self.warnings.append(event)
        elif event.kind == "log":
            if self._blank_error and self._blank_error == event.stream:
                # "ERROR: \r[download] Got error: ... Giving up after 10 retries" arrives as two lines.
                self._blank_error = ""
                self.errors.append(Event("error", _item_of(event.text), event.text, event.stream))
                snap.phase = ""
            else:
                self._apply_log(event.text)
        snap.overall = self._overall()

    def _apply_download(self, data: dict[str, Any]) -> None:
        snap = self._snap
        progress = data.get("p") if isinstance(data.get("p"), dict) else {}
        info = data.get("i") if isinstance(data.get("i"), dict) else {}
        assert isinstance(progress, dict) and isinstance(info, dict)
        status = progress.get("status")
        for key in ("tmpfilename", "filename"):
            if isinstance(progress.get(key), str) and progress[key]:
                self.partials.add(progress[key])
        format_id = str(info.get("format_id") or "")
        downloaded = int(_number(progress.get("downloaded_bytes")) or 0)
        total = int(_number(progress.get("total_bytes")) or _number(progress.get("total_bytes_estimate")) or 0)
        snap.is_live = bool(info.get("is_live")) or snap.is_live
        snap.phase = PHASE_DOWNLOAD
        index, count = progress.get("fragment_index"), progress.get("fragment_count")
        position = (downloaded, index if isinstance(index, int) else -1)
        if status == "finished" or position != self._last_bytes:
            # yt-dlp repeats the same line while it retries; only new bytes or a new part count.
            self._last_bytes = position
            self._moved()
        if status == "finished":
            self._done_parts[format_id] = max(total, downloaded)
            return
        speed = _number(progress.get("speed"))
        eta = _number(progress.get("eta"))
        snap.speed = speed or 0.0
        snap.eta = int(eta) if eta is not None else -1
        # Kept for the share of a download whose size the site doesn't give; never shown as "part 3/9".
        snap.fragment = f"{index}/{count}" if isinstance(index, int) and isinstance(count, int) else ""
        snap.stage = "Recording" if snap.is_live else "Downloading"
        if format_id and total:
            # The live size (exact, or yt-dlp's running estimate for fragments) beats the format list's,
            # which a site often leaves out: a part kept at 0 made the bar read full from the start.
            self._parts[format_id] = total
        done_bytes = sum(self._done_parts.values())
        expected = sum(self._parts.values()) or total
        snap.downloaded = done_bytes + downloaded
        snap.total = max(expected, snap.downloaded) if expected else 0
        if snap.total:
            snap.item_fraction = min(snap.downloaded / snap.total, 0.999)
        elif isinstance(index, int) and isinstance(count, int) and count > 0:
            snap.item_fraction = min(index / count, 0.999)  # no size at all: the share of fragments done
        else:
            snap.item_fraction = 0.0

    def _apply_log(self, text: str) -> None:
        snap = self._snap
        if _PROGRESS_LOG.match(text):
            self._moved()
        listed = _LIST_WRITTEN.match(text)
        if listed:
            self._pending_list = listed.group("path").strip()
            return
        if text.startswith(_GOT_ERROR):
            if snap.phase == PHASE_DOWNLOAD:
                snap.stage = "Connection trouble, trying again"
            return
        position = _ITEM_OF.match(text)
        if position:
            snap.item_index, snap.item_count = int(position.group(1)), int(position.group(2))
            snap.phase = ""  # until the video's details are read and its download starts
            return
        if _ARCHIVED in text:
            snap.items_done += 1
            snap.archived += 1
            snap.phase = ""
            self._moved()
            skipped = _ARCHIVED_ID.match(text)
            if skipped:
                self.archived_ids.append(skipped.group("id"))
                self._updates.append(("state", (skipped.group("id"), "archived", "")))
            elif snap.item_index:
                self._updates.append(("archived_at", snap.item_index))
            return
        page = _PAGE.search(text)
        if page:
            snap.page = int(page.group(1))
            snap.stage = "Reading the playlist"
            self._moved()
            return
        wait = _WAIT.search(text)
        if wait:
            hours, minutes, seconds = (int(part) for part in wait.groups())
            snap.wait_seconds = hours * 3600 + minutes * 60 + seconds
            snap.stage = "Waiting for the stream to start"
            snap.phase = PHASE_WAIT
            return
        if text.startswith("[wait]") or "Waiting for video" in text:
            snap.stage = "Waiting for the stream to start"
            snap.phase = PHASE_WAIT

    def _overall(self) -> float:
        snap = self._snap
        count = snap.item_count or self._expected
        if count <= 1:
            return 1.0 if snap.items_done else snap.item_fraction
        current = 0.0 if snap.item_fraction >= 1.0 else snap.item_fraction
        return min((snap.items_done + current) / count, 1.0)
