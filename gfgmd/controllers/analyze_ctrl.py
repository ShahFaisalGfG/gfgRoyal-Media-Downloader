# analyze_ctrl.py - read a link's details for the Options panel and queue it with chosen options

from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlsplit
from datetime import datetime
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.config.defaults import FormatDefaults
from gfgmd.core.analyze import Analysis, AnalyzeError, analyze, items_spec
from gfgmd.core.archive import archive_path, read_archive_ids
from gfgmd.core.command import Auth
from gfgmd.core.errors import Failure
from gfgmd.core.options import DownloadOptions
from gfgmd.core.schedule import live_launch_time
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sources import Source, canonical_url, source_from_url
from gfgmd.controllers.player_ctrl import language_name
from gfgmd.controllers.queue_ctrl import QueueController, base_options
from gfgmd.models.entry_model import EntryModel
from gfgmd.services.context import VAULT_METHODS, AppContext
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.format import count_media, format_bytes, format_duration
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings


# What reading a link says when it failed for a reason the app doesn't recognize.
_UNREADABLE = "This link couldn't be read. Check that it opens in your browser, then try again."
# Sites whose lists are songs, not videos (for "19 songs").
_MUSIC_SITES = ("soundcloud.com", "bandcamp.com", "mixcloud.com", "audiomack.com", "jiosaavn.com", "deezer.com")
_PAGE = re.compile(r"Downloading (?:API JSON )?page (\d+)", re.IGNORECASE)


class AnalyzeController(QObject):
    """The Options panel: details, qualities, subtitles, entries, and Add to queue."""

    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    notice = Signal(str)

    def __init__(self, context: AppContext, queue: QueueController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._queue = queue
        self._runner = TaskRunner(1, self)
        self._entries = EntryModel(self)
        self._busy = False
        self._stop = threading.Event()
        self._url = ""
        self._source: Source | None = None
        self._result: Analysis | None = None
        self._error = ""
        self._action = ""
        self._status = ""
        # yt-dlp's progress lines arrive on a worker thread; this timer republishes them on the GUI thread.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(400)
        self._status_timer.timeout.connect(self.statusChanged)

    # ── Properties ────────────────────────────────────────────────────────

    @Property(QObject, constant=True)
    def entries(self) -> EntryModel:
        return self._entries

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        """What reading the link is doing, in plain words, while busy."""
        return self._status

    @Property(bool, notify=changed)
    def hasResult(self) -> bool:
        return self._result is not None

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property(str, notify=changed)
    def errorAction(self) -> str:
        """The button the error offers: signin, update_tools, or ""."""
        return self._action

    @Property(str, notify=changed)
    def url(self) -> str:
        return self._url

    @Property(str, notify=changed)
    def siteKey(self) -> str:
        return self._source.site if self._source else ""

    @Property(str, notify=changed)
    def siteLabel(self) -> str:
        return self._context.site(self._source.site).label if self._source else ""

    @Property(str, notify=changed)
    def title(self) -> str:
        return self._result.title if self._result else ""

    @Property(str, notify=changed)
    def uploader(self) -> str:
        return self._result.uploader if self._result else ""

    @Property(str, notify=changed)
    def thumbnail(self) -> str:
        return self._result.thumbnail if self._result else ""

    @Property(bool, notify=changed)
    def isPlaylist(self) -> bool:
        return bool(self._result and self._result.kind == "playlist")

    @Property(bool, notify=changed)
    def selectable(self) -> bool:
        return bool(self._result and self._result.selectable)

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
        if self._result is None:
            return ""
        parts = []
        if self._result.kind == "playlist":
            parts.append(count_media(len(self._result.entries), "audio" if self._music_link() else "video"))
        elif self._result.duration:
            parts.append(format_duration(self._result.duration))
        if self._result.heights:
            parts.append(f"up to {self._result.heights[0]}p")
        if self._result.size_estimate:
            parts.append(f"about {format_bytes(self._result.size_estimate)}")
        return "  ·  ".join(parts)

    def _music_link(self) -> bool:
        """True for a link to music (YouTube Music, SoundCloud, Bandcamp), whose lists hold songs."""
        host = (urlsplit(self._url).hostname or "").lower()
        return host.startswith("music.") or any(host == site or host.endswith("." + site) for site in _MUSIC_SITES)

    @Property(list, constant=True)
    def heightOptions(self) -> list[dict[str, Any]]:
        """The resolution limits (a limit above what a video offers still gets its best quality)."""
        return [{"label": label, "code": code} for label, code in FormatDefaults.HEIGHT_OPTIONS]

    @Property(list, notify=changed)
    def subtitleLangs(self) -> list[str]:
        return list(self._result.subtitle_langs) if self._result else []

    @Property(list, notify=changed)
    def autoSubtitleLangs(self) -> list[str]:
        return list(self._result.auto_subtitle_langs) if self._result else []

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

    # ── Actions ───────────────────────────────────────────────────────────

    @Slot(str)
    def analyze(self, url: str) -> None:
        """Read the link's details in the background."""
        try:
            source = source_from_url(url)
        except ValueError as error:
            self._fail(str(error), "")
            return
        try:
            tools = self._context.tools()
        except RuntimeError as error:
            write_log(f"Reading a link can't start: {error}", "critical")
            self._fail("The download tools aren't installed yet. Click Update tools.", "repair_tools")
            return
        self.cancel()
        self._stop = threading.Event()
        self._url = canonical_url(source, url)
        self._source = source
        self._result = None
        self._error = ""
        self._action = ""
        self._entries.load([], set())
        self._set_busy(True, "Reading the link...")
        self.changed.emit()
        options = base_options(load_settings())
        self._runner.start(self._read, self._url, source, tools, options, self._stop,
                           on_done=self._done, on_error=lambda _message: self._fail(_UNREADABLE, ""))

    def _read(self, url: str, source: Source, tools: Any, options: DownloadOptions,
              stop: threading.Event) -> tuple[Analysis | None, set[str], Failure | None]:
        """On the pool: run yt-dlp with the site's sign-in, then read which entries are archived.

        A link yt-dlp can't read comes back as its Failure, so the panel can offer the fix it needs
        (Sign in, Update yt-dlp) rather than only its message.
        """
        context = self._context
        account = context.account_for(source.site)
        auth: Auth | None = context.browser_auth(account)
        checkout = None
        if account is not None and account["method"] in VAULT_METHODS and context.vault.exists(account["id"]):
            try:
                checkout = context.vault.checkout(account["id"], context.site(source.site),
                                                  context.run_root / f"analyze-{int(time.time() * 1000)}")
                auth = Auth(cookies_file=str(checkout.path))
            except (SecretError, OSError, TimeoutError):
                checkout = None
        try:
            result = analyze(url, tools, context.cache_dir, auth, options, single=not source.is_collection,
                             stop=stop, on_line=self._progress_line)
        except AnalyzeError as error:
            return None, set(), error.failure
        finally:
            if checkout is not None and account is not None:
                context.vault.checkin(account["id"], checkout)
        archived = read_archive_ids(archive_path(context.download_root(options.kind), source, options.profile))
        return result, archived, None

    def _progress_line(self, line: str) -> None:
        # Called from the pool; a plain attribute write the busy poll in QML reads via `status`. yt-dlp's
        # own lines aren't shown: a long playlist says which page it has reached.
        page = _PAGE.search(line)
        if page:
            self._status = f"Reading the playlist (page {page.group(1)})..."

    def _done(self, outcome: tuple[Analysis | None, set[str], Failure | None]) -> None:
        result, archived, failure = outcome
        if self._stop.is_set():
            return
        if result is None:
            # A reason the app knows names it; anything else is said plainly, as nothing was downloading yet.
            known = failure is not None and failure.category.key != "unknown"
            self._fail(failure.category.final if failure is not None and known else _UNREADABLE,
                       failure.category.action if failure else "")
            return
        self._result = result
        self._entries.load(result.entries, archived)
        self._set_busy(False, "")
        self.changed.emit()

    def _fail(self, message: str, action: str) -> None:
        self._error = message
        self._action = action
        self._set_busy(False, "")
        self.changed.emit()

    @Slot(str)
    def signedIn(self, site: str) -> None:
        """A site was just signed in: read the link again when it failed for want of that sign-in."""
        if self._action == "signin" and self._source is not None and self._source.site == site and self._url:
            self.analyze(self._url)

    @Slot()
    def cancel(self) -> None:
        """Stop reading."""
        self._stop.set()
        if self._busy:
            self._set_busy(False, "")

    @Slot()
    def clear(self) -> None:
        """Close the panel's result."""
        self.cancel()
        self._result = None
        self._source = None
        self._url = ""
        self._error = ""
        self._action = ""
        self._entries.load([], set())
        self.changed.emit()

    @Slot("QVariantMap")
    def refreshArchived(self, options: dict[str, Any]) -> None:
        """Mark entries already downloaded in the chosen format (each format has its own archive)."""
        if self._source is None:
            return
        try:
            chosen = DownloadOptions.from_dict({**base_options(load_settings()).to_dict(), **options})
        except ValueError:
            return
        root = self._context.download_root(chosen.kind)
        self._entries.set_archived(read_archive_ids(archive_path(root, self._source, chosen.profile)))

    @Slot("QVariantMap", result=bool)
    def addToQueue(self, options: dict[str, Any]) -> bool:
        """Queue the link with the chosen options and entries; True when queued."""
        if self._result is None or self._source is None:
            return False
        chosen = dict(options)
        items: list[dict[str, Any]] = []
        if self._result.kind == "playlist" and self._result.selectable:
            selected = self._entries.selected()
            if not selected:
                self.notice.emit("Choose at least one video.")
                return False
            if not self._entries.all_selected():
                chosen["items"] = items_spec(entry.index for entry in selected)
            items = [{"id": e.id, "title": e.title, "index": e.index, "duration": e.duration, "url": e.url,
                      "thumbnail": e.thumbnail} for e in selected]
        not_before = 0.0
        if self._result.live_status == "is_upcoming":
            chosen["wait_for_video"] = True
            if self._result.release_timestamp:
                not_before = live_launch_time(self._result.release_timestamp, time.time())
        queued = self._queue.addJob(self._url, chosen, items, self._result.title, self._result.thumbnail, not_before)
        if queued:
            self.clear()
        return queued

    def _set_busy(self, busy: bool, status: str) -> None:
        self._busy = busy
        self._status = status
        if busy:
            self._status_timer.start()
        else:
            self._status_timer.stop()
        self.busyChanged.emit()
        self.statusChanged.emit()

    def shutdown(self) -> None:
        self._stop.set()
        self._runner.shutdown(3000)

