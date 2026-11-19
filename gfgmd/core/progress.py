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
from typing import Any

MARKER = "@@gfgr:"
_BARE_NA = re.compile(r"(?<=[:\[,])\s*NA\s*(?=[,}\]])")
_ITEM_PREFIX = re.compile(r"^\[(?P<extractor>[^\]]+)\] (?P<id>[^:\s]{1,128}): ")
_PAGE = re.compile(r"Downloading (?:API JSON )?page (\d+)", re.IGNORECASE)
_WAIT = re.compile(r"\[wait\] Remaining time until next attempt: (\d+):(\d+):(\d+)")
_ITEM_OF = re.compile(r"^\[download\] Downloading item (\d+) of (\d+)")
_ARCHIVED = "has already been recorded in the archive"

# Post-processor names (yt-dlp class names without "PP") to the stage shown in the UI.
_PP_STAGES = {
    "Merger": "Merging",
    "FFmpegMerger": "Merging",
    "EmbedSubtitle": "Embedding",
    "FFmpegEmbedSubtitle": "Embedding",
    "EmbedThumbnail": "Embedding",
    "FFmpegMetadata": "Embedding",
    "Metadata": "Embedding",
    "ExtractAudio": "Converting",
    "FFmpegExtractAudio": "Converting",
    "VideoRemuxer": "Converting",
    "FFmpegVideoRemuxer": "Converting",
    "VideoConvertor": "Converting",
    "FFmpegSubtitlesConvertor": "Converting",
    "FFmpegThumbnailsConvertor": "Converting",
    "SponsorBlock": "Cutting",
    "ModifyChapters": "Cutting",
    "FFmpegFixupM3u8": "Finalizing",
    "FFmpegFixupM4a": "Finalizing",
    "FFmpegFixupStretched": "Finalizing",
    "FFmpegFixupDuplicateMoov": "Finalizing",
    "FFmpegFixupTimestamp": "Finalizing",
    "MoveFiles": "Finalizing",
    "MoveFilesAfterDownload": "Finalizing",
}


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


def parse_line(stream: str, line: str) -> Event:
    """Classify one output line."""
    text = line.strip()
    if text.startswith(MARKER):
        kind, _, payload = text[len(MARKER):].partition(" ")
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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

    def as_dict(self) -> dict[str, Any]:
        """The snapshot as a dict (for the database and QML)."""
        return dict(self.__dict__)


class ProgressTracker:
    """Fold a job's events into a snapshot; thread-safe so readers feed while the UI polls."""

    def __init__(self, expected_items: int = 0) -> None:
        self._lock = threading.Lock()
        self._snap = Snapshot(item_count=expected_items)
        self._expected = expected_items
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

    def feed(self, stream: str, line: str) -> Event:
        """Parse a line, update the snapshot, and return the event."""
        event = parse_line(stream, line)
        with self._lock:
            self._apply(event)
            self._snap.updated = time.monotonic()
        return event

    def snapshot(self) -> Snapshot:
        """A copy of the current snapshot."""
        with self._lock:
            return Snapshot(**self._snap.__dict__)

    def mark_stage(self, stage: str) -> None:
        """Set the stage from outside (Waiting to retry, Stopped)."""
        with self._lock:
            self._snap.stage = stage

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
            snap.playlist_title = str(data.get("playlist_title") or snap.playlist_title)
            snap.thumbnail = str(data.get("thumbnail") or snap.thumbnail)
            count = data.get("n_entries")
            if isinstance(count, int) and count > 0 and not self._expected:
                snap.item_count = count
            snap.is_live = data.get("live_status") == "is_live"
            snap.stage = "Recording" if snap.is_live else "Starting download"
            snap.item_fraction = 0.0
            snap.downloaded = 0
            snap.total = 0
            self._parts = {}
            self._done_parts = {}
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
            if (progress or {}).get("status") == "started":
                snap.stage = _PP_STAGES.get(name, "Processing")
        elif event.kind == "file":
            self.files.append(data)
            snap.items_done += 1
            snap.item_fraction = 1.0
            snap.stage = "Saved"
        elif event.kind == "entry":
            self.entries.append(data)
        elif event.kind == "pl":
            self.playlist = data
        elif event.kind == "error":
            self.errors.append(event)
        elif event.kind == "warning":
            self.warnings.append(event)
        elif event.kind == "log":
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
        if status == "finished":
            self._done_parts[format_id] = max(total, downloaded)
            return
        speed = _number(progress.get("speed"))
        eta = _number(progress.get("eta"))
        snap.speed = speed or 0.0
        snap.eta = int(eta) if eta is not None else -1
        index, count = progress.get("fragment_index"), progress.get("fragment_count")
        snap.fragment = f"{index}/{count}" if isinstance(index, int) and isinstance(count, int) else ""
        vcodec, acodec = str(info.get("vcodec") or ""), str(info.get("acodec") or "")
        if snap.is_live:
            snap.stage = "Recording"
        elif vcodec == "none" and acodec not in ("", "none"):
            snap.stage = "Downloading audio"
        elif acodec == "none" and vcodec not in ("", "none"):
            snap.stage = "Downloading video"
        else:
            snap.stage = "Downloading"
        if format_id and format_id not in self._parts and total:
            self._parts[format_id] = total
        done_bytes = sum(self._done_parts.values())
        expected = sum(self._parts.values()) or total
        snap.downloaded = done_bytes + downloaded
        snap.total = max(expected, snap.downloaded)
        snap.item_fraction = min(snap.downloaded / snap.total, 0.999) if snap.total else 0.0

    def _apply_log(self, text: str) -> None:
        snap = self._snap
        position = _ITEM_OF.match(text)
        if position:
            snap.item_index, snap.item_count = int(position.group(1)), int(position.group(2))
            return
        if _ARCHIVED in text:
            snap.items_done += 1
            snap.archived += 1
            return
        page = _PAGE.search(text)
        if page:
            snap.page = int(page.group(1))
            snap.stage = "Reading the list"
            return
        wait = _WAIT.search(text)
        if wait:
            hours, minutes, seconds = (int(part) for part in wait.groups())
            snap.wait_seconds = hours * 3600 + minutes * 60 + seconds
            snap.stage = "Waiting for the stream"
            return
        if text.startswith("[wait]") or "Waiting for video" in text:
            snap.stage = "Waiting for the stream"

    def _overall(self) -> float:
        snap = self._snap
        count = snap.item_count or self._expected
        if count <= 1:
            return 1.0 if snap.items_done else snap.item_fraction
        current = 0.0 if snap.item_fraction >= 1.0 else snap.item_fraction
        return min((snap.items_done + current) / count, 1.0)
