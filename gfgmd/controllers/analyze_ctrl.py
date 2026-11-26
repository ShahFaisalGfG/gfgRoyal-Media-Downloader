# analyze_ctrl.py - read a link's details for Download options and queue it with chosen options
#
# Each link read is a _Read: YouTube's quick title and thumbnail (oEmbed, about a second), then
# yt-dlp's details (several seconds). A playlist's or channel's videos arrive page by page. Reading
# starts when a link is pasted (prefetch), and finished reads are kept for a while, so opening
# Download options is often instant. The panel shows one read at a time; a read that finishes after
# another link was opened only fills the cache.

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.config.defaults import FormatDefaults
from gfgmd.core.analyze import Analysis, AnalyzeError, Entry, analyze, analyze_list, entry_from, items_spec
from gfgmd.core.archive import archive_path, read_archive_ids
from gfgmd.core.command import Auth
from gfgmd.core.errors import Failure
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import is_container
from gfgmd.core.quick_info import QuickInfo, quick_info
from gfgmd.core.schedule import live_launch_time
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sources import Source, canonical_url, single_video, source_from_url, video_link
from gfgmd.controllers.queue_ctrl import QueueController, base_options, with_network
from gfgmd.models.entry_model import EntryModel
from gfgmd.services.context import VAULT_METHODS, AppContext
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.format import count_media, format_bytes, format_duration
from gfgmd.utils.languages import language_name, subtitle_tracks
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings


# What reading a link says when it failed for a reason the app doesn't recognize.
_UNREADABLE = "This link couldn't be read. Check that it opens in your browser, then try again."
_NO_TOOLS = "The download tools aren't installed yet. Click Update tools."
# Sites whose lists are songs, not videos (for "19 songs").
_MUSIC_SITES = ("soundcloud.com", "bandcamp.com", "mixcloud.com", "audiomack.com", "jiosaavn.com", "deezer.com")
_PAGE = re.compile(r"Downloading (?:API JSON )?page (\d+)", re.IGNORECASE)
# Finished reads are kept this long, and this many at most, for opening the same link again.
KEEP_SECONDS = 600
KEEP_READS = 20


@dataclass(eq=False)
class _Read:
    """One link being read, or read."""

    url: str  # the link yt-dlp reads (a video inside a playlist: the video's own link, unless the playlist is wanted)
    source: Source
    key: tuple[str, int]  # the link and the signed-in account it was read with
    streams: bool  # a YouTube playlist or channel: its videos arrive as each page is read
    stop: threading.Event = field(default_factory=threading.Event)
    finished_at: float = 0.0
    quick: QuickInfo | None = None
    result: Analysis | None = None
    archived: set[str] = field(default_factory=set)
    error: str = ""
    action: str = ""
    status: str = "Reading the link..."
    # Videos read so far (the worker adds them; the GUI shows them), and whether one is itself a list.
    entries: list[Entry] = field(default_factory=list)
    containers: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def done(self) -> bool:
        return self.finished_at > 0


class AnalyzeController(QObject):
    """Download options: details, qualities, subtitles, entries, and Download."""

    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    notice = Signal(str)

    def __init__(self, context: AppContext, queue: QueueController, parent: QObject | None = None,
                 quick_fetch: Any = None) -> None:
        super().__init__(parent)
        self._context = context
        self._queue = queue
        # Reads in one pool and the quick titles in another, so a title never waits for a read.
        self._runner = TaskRunner(2, self)
        self._quick_runner = TaskRunner(2, self)
        # The app reads YouTube's oEmbed page; tests pass a fake (None skips the quick title).
        self._quick_fetch = quick_fetch
        self._entries = EntryModel(self)
        self._reads: dict[tuple[str, int], _Read] = {}
        self._current: _Read | None = None
        self._shown = 0  # how many of the current read's entries the list shows
        # The link as given, and for a video inside a playlist which one is read ("video", "playlist").
        self._link = ""
        self._scope = ""
        # Several links shown at once (Smart Mode off): one set of choices for all of them.
        self._links: list[str] = []
        self._error = ""
        self._action = ""
        # Worker threads write a read's status and entries; this timer shows them on the GUI thread.
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self._show_progress)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def _result(self) -> Analysis | None:
        return self._current.result if self._current else None

    @Property(QObject, constant=True)
    def entries(self) -> EntryModel:
        return self._entries

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._current is not None and not self._current.done

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        """What reading the link is doing, in plain words, while busy."""
        return self._current.status if self._current is not None and not self._current.done else ""

    @Property(bool, notify=changed)
    def hasResult(self) -> bool:
        """True when the choices can show: the video's details are read, a list's videos are arriving,
        or several links are shown."""
        if self._links:
            return True
        current = self._current
        return current is not None and not current.error and (current.result is not None or current.streams)

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        """True when Download can queue: everything is read (or several links are shown)."""
        return bool(self._links) or self._result is not None

    @Property(int, notify=changed)
    def linkCount(self) -> int:
        """How many links share the choices (0 when one link is read)."""
        return len(self._links)

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._current.error if self._current is not None and self._current.error else self._error

    @Property(str, notify=changed)
    def errorAction(self) -> str:
        """The button the error offers: signin, update_tools, or ""."""
        return self._current.action if self._current is not None and self._current.error else self._action

    @Property(str, notify=changed)
    def url(self) -> str:
        return self._current.url if self._current else ""

    @Property(str, notify=changed)
    def link(self) -> str:
        """The link as given (a video inside a playlist keeps its list, for switching between the two)."""
        return self._link

    @Property(bool, notify=changed)
    def inPlaylist(self) -> bool:
        """True for a link to a video inside a playlist, which can be read as the video or the playlist."""
        return self._scope != ""

    @Property(str, notify=changed)
    def scope(self) -> str:
        """For a video inside a playlist: "video" or "playlist", whichever is read."""
        return self._scope

    @Property(str, notify=changed)
    def siteKey(self) -> str:
        return self._current.source.site if self._current else ""

    @Property(str, notify=changed)
    def siteLabel(self) -> str:
        return self._context.site(self._current.source.site).label if self._current else ""

    @Property(str, notify=changed)
    def title(self) -> str:
        if self._links:
            return f"{len(self._links)} links"
        current = self._current
        if current is None:
            return ""
        if current.result is not None:
            return current.result.title
        return current.quick.title if current.quick else ""

    @Property(str, notify=changed)
    def uploader(self) -> str:
        current = self._current
        if current is None:
            return ""
        if current.result is not None and current.result.uploader:
            return current.result.uploader
        return current.quick.uploader if current.quick else ""

    @Property(str, notify=changed)
    def thumbnail(self) -> str:
        current = self._current
        if current is None:
            return ""
        if current.result is not None and current.result.thumbnail:
            return current.result.thumbnail
        return current.quick.thumbnail if current.quick else ""

    @Property(bool, notify=changed)
    def isPlaylist(self) -> bool:
        current = self._current
        if current is None:
            return False
        return current.result.kind == "playlist" if current.result is not None else current.streams and not current.error

    @Property(bool, notify=changed)
    def selectable(self) -> bool:
        current = self._current
        if current is None:
            return False
        return current.result.selectable if current.result is not None else current.streams and not current.containers

    @Property(str, notify=changed)
    def liveStatus(self) -> str:
        """is_live, is_upcoming, was_live, not_live, or ""."""
        return self._result.live_status if self._result else ""

    @Property(str, notify=changed)
    def startsText(self) -> str:
        """When a scheduled stream or premiere begins."""
        if self._result and self._result.release_timestamp and self._result.live_status == "is_upcoming":
            return datetime.fromtimestamp(self._result.release_timestamp).strftime("%a %d %b, %H:%M")
        return ""

    @Property(str, notify=changed)
    def details(self) -> str:
        """Duration, size estimate, and entry count in one line."""
        if self._links:
            return "One set of choices for every link"
        current = self._current
        if current is None:
            return ""
        result = current.result
        if result is None:
            return f"{count_media(self._shown, self._media_kind())} so far" if current.streams and self._shown else ""
        parts = []
        if result.kind == "playlist":
            parts.append(count_media(len(result.entries), self._media_kind()))
        elif result.duration:
            parts.append(format_duration(result.duration))
        if result.heights:
            parts.append(f"up to {result.heights[0]}p")
        if result.size_estimate:
            parts.append(f"about {format_bytes(result.size_estimate)}")
        return "  ·  ".join(parts)

    def _media_kind(self) -> str:
        """"audio" for a link to music (YouTube Music, SoundCloud, Bandcamp), whose lists hold songs."""
        host = (urlsplit(self._current.url if self._current else "").hostname or "").lower()
        music = host.startswith("music.") or any(host == site or host.endswith("." + site) for site in _MUSIC_SITES)
        return "audio" if music else "video"

    @Property(list, constant=True)
    def heightOptions(self) -> list[dict[str, Any]]:
        """The resolution limits (a limit above what a video offers still gets its best quality)."""
        return [{"label": label, "code": code} for label, code in FormatDefaults.HEIGHT_OPTIONS]

    @Property(list, notify=changed)
    def subtitleTracks(self) -> list[dict[str, Any]]:
        """The video's subtitles ({code, name, kind}): the creator's, then YouTube's automatic captions of
        its speech, then their machine translations; empty for a list, whose videos differ."""
        result = self._result
        if result is None or result.kind != "video":
            return []
        return subtitle_tracks(result.subtitle_langs, result.auto_subtitle_langs)

    @Property(list, notify=changed)
    def audioTracks(self) -> list[dict[str, Any]]:
        """The video's audio languages ({code, label, original}), original first; empty with just one."""
        if self._result is None:
            return []
        return [{"code": track.code, "label": language_name(track.code) or track.label, "original": track.original}
                for track in self._result.audio_tracks]

    @Property(str, notify=changed)
    def language(self) -> str:
        """The video's own language code ("" when the site doesn't say)."""
        return self._result.language if self._result else ""

    # ── Reading ───────────────────────────────────────────────────────────

    @Slot(str)
    @Slot(str, str)
    def analyze(self, url: str, scope: str = "") -> None:
        """Show a link's details, reading them unless they were read (or are being read) already.

        For a link to a video inside a playlist, `scope` says which is read: "video" or "playlist";
        without it, the answer remembered in Preferences, else the video.
        """
        self._links = []
        try:
            source = source_from_url(url)
        except ValueError as error:
            self._show_failure(str(error), "")
            return
        self._link, self._scope = url, ""
        if source.video_id:
            self._scope = scope if scope in ("video", "playlist") else self._remembered_scope()
            if self._scope == "video":
                url, source = video_link(source, url), single_video(source)
        read = self._read_for(url, source)
        if read is None:
            self._show_failure(_NO_TOOLS, "repair_tools")
            return
        self._show(read)

    @Slot(str)
    def prefetch(self, url: str) -> None:
        """Start reading a pasted link before Download options open; nothing shows until they do."""
        try:
            source = source_from_url(url)
        except ValueError:
            return
        if source.video_id and self._remembered_scope() == "video":
            url, source = video_link(source, url), single_video(source)
        # Only the newest pasted link is worth reading ahead; an older one still being read stops.
        for read in list(self._reads.values()):
            if read is not self._current and not read.done:
                read.stop.set()
                self._reads.pop(read.key, None)
        self._read_for(url, source)

    @Slot("QVariantList")
    def showLinks(self, links: list[str]) -> None:
        """Show several links with one set of choices (Smart Mode off); one link is read as usual."""
        links = [str(link) for link in links if str(link).strip()]
        if len(links) == 1:
            self.analyze(links[0])
            return
        self._current, self._links, self._link, self._scope = None, links, "", ""
        self._error = self._action = ""
        self._entries.load([], set())
        self._tick.stop()
        self.changed.emit()
        self.busyChanged.emit()
        self.statusChanged.emit()

    def _remembered_scope(self) -> str:
        answer = load_settings().get("downloads", {}).get("playlist_links", "ask")
        return "playlist" if answer == "playlist" else "video"

    def _read_for(self, url: str, source: Source) -> _Read | None:
        """The read of this link with today's sign-in: kept from before, or started now (None without tools)."""
        account = self._context.account_for(source.site)
        key = (canonical_url(source, url), int(account["id"]) if account else 0)
        self._forget_old()
        read = self._reads.get(key)
        if read is not None and not read.error:
            return read
        try:
            tools = self._context.tools()
        except RuntimeError as error:
            write_log(f"Reading a link can't start: {error}", "critical")
            return None
        streams = source.site == "youtube" and source.kind in ("playlist", "channel")
        read = _Read(key[0], source, key, streams)
        self._reads[key] = read
        settings = load_settings()
        kind = "audio" if settings.get("downloads", {}).get("kind") == "audio" else "video"
        options = with_network(base_options(settings, kind), settings)
        self._runner.start(self._work, read, tools, options,
                           on_done=lambda outcome, r=read: self._finished(r, outcome),
                           on_error=lambda _message, r=read: self._finished(r, (None, None)))
        if self._quick_fetch is not None:
            self._quick_runner.start(quick_info, source, read.url, self._quick_fetch,
                                     on_done=lambda info, r=read: self._quick_done(r, info),
                                     on_error=lambda _message: None)
        return read

    def _forget_old(self) -> None:
        """Drop finished reads past their time, and the oldest beyond the limit (never the one shown)."""
        now = time.monotonic()
        done = sorted((read for read in self._reads.values() if read.done and read is not self._current),
                      key=lambda read: read.finished_at)
        for read in done:
            if now - read.finished_at > KEEP_SECONDS or len(self._reads) > KEEP_READS:
                self._reads.pop(read.key, None)

    def _work(self, read: _Read, tools: Any, options: DownloadOptions) -> tuple[Analysis | None, Failure | None]:
        """On the pool: run yt-dlp with the site's sign-in, after reading which entries are archived.

        A link yt-dlp can't read comes back as its Failure, so the panel can offer the fix it needs
        (Sign in, Update yt-dlp) rather than only its message.
        """
        context = self._context
        account = context.account_for(read.source.site)
        auth: Auth | None = context.browser_auth(account)
        checkout = None
        if account is not None and account["method"] in VAULT_METHODS and context.vault.exists(account["id"]):
            try:
                checkout = context.vault.checkout(account["id"], context.site(read.source.site),
                                                  context.run_root / f"analyze-{int(time.time() * 1000)}")
                auth = Auth(cookies_file=str(checkout.path))
            except (SecretError, OSError, TimeoutError):
                checkout = None
        read.archived = read_archive_ids(archive_path(context.download_root(options.kind), read.source, options.profile))
        try:
            if read.streams:
                result = analyze_list(read.url, tools, context.cache_dir, auth, options, stop=read.stop,
                                      on_entry=lambda data: self._listed(read, data),
                                      on_line=lambda line: self._progress_line(read, line))
            else:
                result = analyze(read.url, tools, context.cache_dir, auth, options,
                                 single=not read.source.is_collection, stop=read.stop,
                                 on_line=lambda line: self._progress_line(read, line))
        except AnalyzeError as error:
            return None, error.failure
        finally:
            if checkout is not None and account is not None:
                context.vault.checkin(account["id"], checkout)
        return result, None

    @staticmethod
    def _listed(read: _Read, data: dict[str, Any]) -> None:
        # On the pool: one video of a list arrived; the GUI shows it at its next tick.
        with read.lock:
            entry = entry_from(data, len(read.entries) + 1)
            if entry is not None:
                read.entries.append(entry)
            read.containers = read.containers or is_container(data)
            read.status = f"Reading the list ({count_media(len(read.entries), 'video')} so far)..."

    @staticmethod
    def _progress_line(read: _Read, line: str) -> None:
        # On the pool; yt-dlp's own lines aren't shown: a long playlist says which page it has reached.
        page = _PAGE.search(line)
        if page and not read.streams:
            read.status = f"Reading the playlist (page {page.group(1)})..."

    def _quick_done(self, read: _Read, info: QuickInfo | None) -> None:
        read.quick = info
        if read is self._current and info is not None:
            self.changed.emit()

    def _finished(self, read: _Read, outcome: tuple[Analysis | None, Failure | None]) -> None:
        result, failure = outcome
        read.finished_at = time.monotonic()
        if result is None:
            if read.stop.is_set():
                self._reads.pop(read.key, None)
                return
            # A reason the app knows names it; anything else is said plainly, as nothing was downloading yet.
            known = failure is not None and failure.category.key != "unknown"
            read.error = failure.category.final if failure is not None and known else _UNREADABLE
            read.action = failure.category.action if failure is not None else ""
        else:
            read.result = result
        if read is self._current:
            self._show(read)

    # ── Showing ───────────────────────────────────────────────────────────

    def _show(self, read: _Read) -> None:
        """Make this read the one Download options shows."""
        fresh = read is not self._current
        self._current = read
        self._error = self._action = ""
        if read.result is not None and not read.streams:
            self._entries.load(read.result.entries, read.archived)
            self._shown = len(read.result.entries)
        else:
            if fresh:
                self._entries.start(read.archived)
                self._shown = 0
            self._show_entries(read.result.entries if read.result is not None else None)
        if read.done:
            self._tick.stop()
        else:
            self._tick.start()
        self.changed.emit()
        self.busyChanged.emit()
        self.statusChanged.emit()

    def _show_entries(self, final: list[Entry] | None = None) -> None:
        """Add the current list's videos read since the last look."""
        read = self._current
        if read is None:
            return
        with read.lock:
            arrived = (final if final is not None else read.entries)[self._shown:]
        if arrived:
            self._shown += len(arrived)
            self._entries.extend(arrived)

    def _show_progress(self) -> None:
        if self._current is None or self._current.done:
            self._tick.stop()
            return
        before = self._shown
        self._show_entries()
        if self._shown != before:
            self.changed.emit()
        self.statusChanged.emit()

    def _show_failure(self, message: str, action: str) -> None:
        self._current, self._links = None, []
        self._error, self._action = message, action
        self._entries.load([], set())
        self._tick.stop()
        self.changed.emit()
        self.busyChanged.emit()
        self.statusChanged.emit()

    @Slot(str)
    def signedIn(self, site: str) -> None:
        """A site was just signed in: read the link again when it failed for want of that sign-in."""
        current = self._current
        if current is not None and current.action == "signin" and current.source.site == site and self._link:
            for read in [read for read in self._reads.values() if read.source.site == site]:
                self._reads.pop(read.key, None)
            self.analyze(self._link, self._scope)

    @Slot()
    def cancel(self) -> None:
        """Stop reading the link shown (a finished read stays kept)."""
        current = self._current
        if current is not None and not current.done:
            current.stop.set()
            self._reads.pop(current.key, None)
            self._current = None
            self._tick.stop()
            self.changed.emit()
            self.busyChanged.emit()
            self.statusChanged.emit()

    @Slot()
    def clear(self) -> None:
        """Close what Download options show."""
        self.cancel()
        self._current, self._links, self._link, self._scope = None, [], "", ""
        self._error = self._action = ""
        self._entries.load([], set())
        self.changed.emit()
        self.busyChanged.emit()

    @Slot("QVariantMap")
    def refreshArchived(self, options: dict[str, Any]) -> None:
        """Mark entries already downloaded in the chosen format (each format has its own archive)."""
        current = self._current
        if current is None:
            return
        try:
            chosen = DownloadOptions.from_dict({**base_options(load_settings()).to_dict(), **options})
        except ValueError:
            return
        root = self._context.download_root(chosen.kind)
        current.archived = read_archive_ids(archive_path(root, current.source, chosen.profile))
        self._entries.set_archived(current.archived)

    # ── Queueing ──────────────────────────────────────────────────────────

    @Slot("QVariantMap", result=bool)
    def addToQueue(self, options: dict[str, Any]) -> bool:
        """Queue the link (or the links) with the chosen options and entries; True when queued."""
        if self._links:
            queued = self._queue.addLinksWith("\n".join(self._links), options) > 0
            if queued:
                self.clear()
            return queued
        current = self._current
        if current is None or current.result is None:
            return False
        result = current.result
        chosen = dict(options)
        items: list[dict[str, Any]] = []
        if result.kind == "playlist" and result.selectable:
            selected = self._entries.selected()
            if not selected:
                self.notice.emit("Choose at least one video.")
                return False
            if not self._entries.all_selected():
                chosen["items"] = items_spec(entry.index for entry in selected)
            items = [{"id": e.id, "title": e.title, "index": e.index, "duration": e.duration, "url": e.url,
                      "thumbnail": e.thumbnail} for e in selected]
        not_before = 0.0
        if result.live_status == "is_upcoming":
            chosen["wait_for_video"] = True
            if result.release_timestamp:
                not_before = live_launch_time(result.release_timestamp, time.time())
        queued = self._queue.addJob(current.url, chosen, items, result.title, result.thumbnail, not_before)
        if queued:
            self.clear()
        return queued

    def shutdown(self) -> None:
        for read in self._reads.values():
            read.stop.set()
        self._runner.shutdown(3000)
        self._quick_runner.shutdown(3000)
