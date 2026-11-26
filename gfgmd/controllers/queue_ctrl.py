# queue_ctrl.py - the download queue: adding, running, pausing, retrying, and finishing jobs
#
# Jobs live in library.db, so the queue survives restarts and crashes. Each running job is a
# JobExecutor on the task pool; a 4 Hz timer copies its progress into the list model, totals, and
# the taskbar. The pump starts queued jobs while there is room: within the concurrency limit, the
# site's own limit, after any scheduled start time, and never two jobs sharing one archive.

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QCoreApplication, QEventLoop, QObject, QTimer, Signal, Slot

from gfgmd.config.defaults import DownloadDefaults, FormatDefaults
from gfgmd.controllers.queue_rows import (ROLES, collection_values, entry_key, entry_row, job_key, job_row, kind_of,
                                          running_values)
from gfgmd.core.archive import archive_path, read_archive_ids
from gfgmd.core.auth import Checkout
from gfgmd.core.command import SESSION_ARCHIVE, Auth, RunPaths
from gfgmd.core.extract import AudioExtractor, ExtractSpec
from gfgmd.core.jobs import STALL_SECONDS, JobExecutor, JobResult, JobSpec, Runner
from gfgmd.core.lyrics import Fetch
from gfgmd.core.naming import AUDIO_EXTENSIONS, group_of, remove_empty_scratch, remove_partials
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import Event, Snapshot
from gfgmd.core.runner import run_to_completion
from gfgmd.core.schedule import limit_at, next_queue_start, per_job_limit
from gfgmd.core.secret_store import SecretError, wipe
from gfgmd.core.sources import Source, as_link, canonical_url, single_video, source_from_url, video_link
from gfgmd.core.store import ACTIVE_STATES
from gfgmd.models.list_model import DictListModel
from gfgmd.services import power
from gfgmd.services.context import VAULT_METHODS, AppContext
from gfgmd.services.notifier import Notifier
from gfgmd.services.recycle import failure_notice, recycle_saved
from gfgmd.services.taskbar import INDETERMINATE, NORMAL, PAUSED, TaskbarProgress
from gfgmd.services.tasks import TaskRunner
from gfgmd.services.thumbnails import cache_file
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.format import count_media, format_bytes
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings, save_settings

POLL_MS = 250
TICK_MS = 15_000
# Playlists with up to this many videos open in the list; longer ones start closed.
OPEN_UP_TO = 50
_WAITING = ("queued", "scheduled", "waiting_live")
_LIVE_STATES = ("running", "retry_wait")
_CLEARABLE = ("done", "cancelled")
# What the Extract audio dialog chooses, over the audio preferences.
EXTRACT_CHOICES = ("audio_format", "audio_quality", "cover", "lyrics", "lyrics_online", "embed_thumbnail",
                   "embed_metadata", "embed_chapters")
# Unfinished files a stopped download reported, kept in its scratch folder so Cancel and Remove can
# delete them after a pause or a restart, when no download is running to report them.
PARTIALS_FILE = "partials.json"


# How strongly each reason stops a running download: a later, weaker one (Pause all after Cancel, the
# app quitting after Remove) doesn't replace it.
_STOP_RANK = {"restart": 0, "shutdown": 1, "pause_all": 2, "pause": 2, "cancel": 3, "remove": 4, "remove_files": 5}


@dataclass
class _Running:
    """A job on the pool: its executor once built, why it is being stopped, and its saved files."""

    job_id: int
    archive: str
    site: str  # "" for an audio extraction, which no site limits
    live: bool
    root: str = ""  # the download folder it saves into
    executor: JobExecutor | AudioExtractor | None = None
    stop_reason: str = ""
    files: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def stop(self, reason: str) -> None:
        if _STOP_RANK.get(reason, 0) >= _STOP_RANK.get(self.stop_reason, -1):
            self.stop_reason = reason
        if self.executor is not None:
            self.executor.stop()


def base_options(settings: dict[str, Any], kind: str = "video") -> DownloadOptions:
    """Preferences' Video or Audio defaults as download options: what Smart mode downloads with, and
    what Download options start from. Audio has its own "Save in the file" choices."""
    formats = settings.get("formats", {})
    downloads = settings.get("downloads", {})
    audio = kind == "audio"
    container = formats.get("container", "mp4")
    langs = [code for code in formats.get("audio_langs", []) if isinstance(code, str)]
    # Extra audio tracks need languages and an MP4 or MKV file; otherwise the original track alone.
    tracks = formats.get("audio_tracks", "original")
    if tracks != "original" and (not langs or container not in ("mp4", "mkv")):
        tracks, langs = "original", []
    return DownloadOptions.from_dict({
        "kind": "audio" if audio else "video",
        "max_height": formats.get("max_height", 0),
        "container": container,
        "codec_profile": formats.get("codec_profile", "balanced"),
        "audio_tracks": tracks,
        "audio_langs": langs,
        "audio_format": formats.get("audio_format", "mp3"),
        "audio_quality": formats.get("audio_quality", FormatDefaults.DEFAULT_AUDIO_QUALITY),
        "cover": formats.get("cover", "square"),
        "subtitles": formats.get("subtitles", "none"),
        "subtitle_format": formats.get("subtitle_format", "srt"),
        "lyrics": formats.get("lyrics", True),
        "lyrics_online": formats.get("lyrics_online", True),
        "subtitle_langs": formats.get("subtitle_langs", "en.*"),
        "auto_subtitles": formats.get("auto_subtitles", False),
        "embed_thumbnail": formats.get("audio_embed_cover" if audio else "embed_thumbnail", True),
        "embed_metadata": formats.get("audio_embed_metadata" if audio else "embed_metadata", True),
        "embed_chapters": formats.get("audio_embed_chapters" if audio else "embed_chapters", True),
        "sponsorblock": formats.get("sponsorblock", "off"),
        "sponsorblock_categories": formats.get("sponsorblock_categories", ["sponsor"]),
        "filename_style": downloads.get("filename_style", "title-quality"),
    })


def with_network(options: DownloadOptions, settings: dict[str, Any]) -> DownloadOptions:
    """These options with the proxy and IPv4 choices of Preferences > Network, which reading a link
    and checking a subscription use as downloads do."""
    network = settings.get("network", {})
    return options.with_changes(proxy=str(network.get("proxy", "")), force_ipv4=bool(network.get("force_ipv4", False)))


def source_of(job: dict[str, Any]) -> Source:
    """The Source a stored job was classified as."""
    return Source(job["source_kind"], job["source_id"], job["site"], job["tab"])


class QueueController(QObject):
    """The download queue for QML."""

    changed = Signal()
    # The queue finished with Quit chosen for when it is done; the app quits (see app.py).
    quitRequested = Signal()
    busyChanged = Signal()
    notice = Signal(str)
    # A finished file, for the library (history id, path).
    fileSaved = Signal(int, str)
    # Library records went with files moved to the Recycle Bin.
    filesRemoved = Signal()
    # The queue finished with an action chosen: QML shows a countdown before it happens.
    whenDoneCountdown = Signal(str)
    # A job needs the user to sign in to a site (site key).
    signInNeeded = Signal(str)
    # Links to a video inside a playlist wait for "this video or the whole playlist?" (how many wait);
    # QML asks and answers with answerPlaylist.
    playlistQuestion = Signal(int)
    # Smart mode is off and links came from outside the link box: QML shows them in Download options
    # (the links, and "video" or "audio").
    optionsRequested = Signal(list, str)
    # A setting was saved here (the remembered "video or playlist" answer), for Preferences to show.
    settingsSaved = Signal()

    def __init__(self, context: AppContext, tools: ToolManager, notifier: Notifier,
                 parent: QObject | None = None, runner: Runner = run_to_completion,
                 lyrics_fetch: Fetch | None = None, stall_seconds: float = STALL_SECONDS,
                 release_player: Callable[[list[str]], None] | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._tools = tools
        self._notifier = notifier
        self._program_runner = runner
        # The built-in players' release (PlayerController.release_files); see release_files.
        self._release_player = release_player or (lambda _paths: None)
        # The app passes lyrics.fetch_json; tests leave it out, so they never reach LRCLIB.
        self._lyrics_fetch = lyrics_fetch
        # How long a video may download without moving before it is set aside (see JobExecutor).
        self._stall_seconds = stall_seconds
        self._model = DictListModel(ROLES, "rowKey", self)
        self._runner = TaskRunner(DownloadDefaults.MAX_CONCURRENT + 2, self)
        self._running: dict[int, _Running] = {}
        self._snapshots: dict[int, Snapshot] = {}
        # Each download's newest saved file (for its Play button), read from the library once per job.
        self._last_files: dict[int, str] = {}
        # Whether each playlist's videos show under it (this session), and which video each running
        # playlist is on.
        self._expanded: dict[int, bool] = {}
        self._current: dict[int, str] = {}
        # Each running playlist's current video and its place in the list: (video id, number).
        self._numbers: dict[int, tuple[str, int]] = {}
        # How many links the latest add queued (not counting ones already in the list).
        self._added_last = 0
        # Links to a video inside a playlist, with their choices, waiting for answerPlaylist.
        self._held: list[tuple[str, DownloadOptions]] = []
        self._paused = False
        self._hold_until = 0.0
        self._applied_limit = 0
        self._when_done = "nothing"
        self._worked = False
        self._speed = 0.0
        self._progress = 0.0
        self._summary = ""
        # While an action runs on several downloads, the list refreshes once at the end and the
        # Recycle Bin notice counts them all (see _batch).
        self._batching = False
        self._batch_changed = False
        self._batch_recycled = 0
        self._taskbar = TaskbarProgress()
        self._awake = False
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._refresh_running)
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        recovered = context.store.recover()
        if recovered:
            write_log(f"Resuming {len(recovered)} download(s) interrupted last time", "general")
        self._clear_run_folder()
        # Also here, not only on closing: a crash or a power cut skips the clean-up there.
        self._clear_last_session()
        self._apply_schedule_settings()
        self._sync_model()
        self._tick.start()
        # Downloads stopped when the app last closed go on as soon as the window is up, not at the first tick.
        QTimer.singleShot(0, self, self._on_tick)

    # ── Properties ────────────────────────────────────────────────────────

    @Property(QObject, constant=True)
    def model(self) -> DictListModel:
        return self._model

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        """True while downloads run (the updater waits for them)."""
        return bool(self._running)

    @Property(int, notify=changed)
    def runningCount(self) -> int:
        return len(self._running)

    @Property(int, notify=changed)
    def jobCount(self) -> int:
        """How many downloads the list holds (not counting a playlist's videos under it)."""
        return len(self._context.store.jobs())

    @Property(int, notify=changed)
    def waitingCount(self) -> int:
        """Downloads waiting for their turn or their start time."""
        return len(self._context.store.jobs(_WAITING))

    @Property(int, notify=changed)
    def finishedCount(self) -> int:
        """Downloads Clear finished would remove."""
        return len(self._context.store.jobs(_CLEARABLE))

    @Property(bool, notify=changed)
    def paused(self) -> bool:
        return self._paused

    @Property(float, notify=changed)
    def progress(self) -> float:
        """Overall progress of the running downloads (0..1)."""
        return self._progress

    @Property(str, notify=changed)
    def speedText(self) -> str:
        return f"{format_bytes(int(self._speed))}/s" if self._speed > 0 else ""

    @Property(str, notify=changed)
    def holdText(self) -> str:
        """When the queue starts, while a start time holds it back."""
        if self._hold_until > time.time():
            return datetime.fromtimestamp(self._hold_until).strftime("%H:%M")
        return ""

    @Property(str, notify=changed)
    def summary(self) -> str:
        """The latest finished download's one-line result."""
        return self._summary

    @Property(str, notify=changed)
    def whenDone(self) -> str:
        return self._when_done

    @Property(str, notify=changed)
    def lastFolder(self) -> str:
        """The download root, for Open folder."""
        return str(self._context.download_root())

    # ── Adding ────────────────────────────────────────────────────────────

    @Slot(str, str, result=int)
    @Slot(str, str, str, result=int)
    def addLinks(self, text: str, kind: str, scope: str = "") -> int:
        """Queue every link in text (one per line) with the Video or Audio defaults from Preferences;
        returns how many are now in the list or waiting for the "video or playlist" question.

        `scope` answers that question for links to a video inside a playlist ("video" or "playlist");
        without it the remembered answer applies, or the links wait while QML asks (playlistQuestion).
        """
        try:
            options = base_options(load_settings(), kind)
        except ValueError as error:
            write_log(f"The {kind} defaults can't be used: {error}", "critical")
            self.notice.emit("A choice in Preferences can't be used any more. Open Preferences and choose again.")
            return 0
        return self._queue_links(text, options, scope)

    @Slot(str, str, result=int)
    def receiveLinks(self, text: str, kind: str) -> int:
        """Links from outside the link box (the browser extension, the tray, drag and drop, the copied-link
        offer, a second launch): with Smart mode on they download at once; off, QML opens Download
        options for them (optionsRequested) and nothing is queued yet."""
        if load_settings().get("downloads", {}).get("smart_mode", True):
            return self.addLinks(text, kind)
        links = [as_link(word) for word in text.replace(",", "\n").split() if word.strip()]
        if links:
            self.optionsRequested.emit(links, "audio" if kind == "audio" else "video")
        return len(links)

    @Slot(str, bool)
    def answerPlaylist(self, scope: str, remember: bool) -> None:
        """The answer to "video or playlist" for the links waiting on it: "video", "playlist", or "" to drop them.
        Remembering it saves the answer, so later such links don't ask (Preferences > Downloads changes it)."""
        held, self._held = self._held, []
        if scope not in ("video", "playlist"):
            return
        if remember:
            settings = load_settings()
            settings.setdefault("downloads", {})["playlist_links"] = scope
            if save_settings(settings):
                self.settingsSaved.emit()
            else:
                write_log("The answer for links to a video in a playlist couldn't be saved", "critical")
        for link, options in held:
            self._queue_links(link, options, scope)

    def _playlist_answer(self) -> str:
        """The remembered answer for a video inside a playlist, "" when the app asks each time."""
        answer = load_settings().get("downloads", {}).get("playlist_links", "ask")
        return answer if answer in ("video", "playlist") else ""

    def download_again(self, url: str, kind: str, extension: str) -> None:
        """Queue a link even if it was downloaded before (the Library's Download again), as the same type
        of file as the one in the Library: a song stays a song, an MKV stays an MKV. The rest of the
        choices are the Video or Audio defaults from Preferences."""
        settings = load_settings()
        try:
            switch = settings.get("downloads", {}).get("kind", "video")
            options = base_options(settings, kind if kind in ("audio", "video") else switch)
            audio_format = {"ogg": "vorbis"}.get(extension, extension)
            if options.kind == "audio" and audio_format in FormatDefaults.AUDIO_FORMATS:
                options = options.with_changes(audio_format=audio_format)
            elif options.kind == "video" and extension in FormatDefaults.CONTAINERS:
                options = options.with_changes(container=extension)
            options = options.with_changes(ignore_archive=True)
        except ValueError as error:
            write_log(f"Download again of {url} couldn't use its choices: {error}", "critical")
            options = base_options(settings).with_changes(ignore_archive=True)
        if self._queue_links(url, options, "video") and self._added_last:
            self.notice.emit("Added to Downloads.")

    def _queue_links(self, text: str, options: DownloadOptions, scope: str = "") -> int:
        """Queue every link in text with these choices; returns how many are now in the list or wait
        for the "video or playlist" answer (see addLinks)."""
        links = [as_link(word) for word in text.replace(",", "\n").split() if word.strip()]
        scope = scope or self._playlist_answer()
        added, listed, held, problems = 0, 0, 0, []
        for link in links:
            try:
                source = source_from_url(link)
            except ValueError as error:
                problems.append(str(error))
                continue
            if source.video_id and scope != "playlist":
                if scope != "video":
                    self._held.append((link, options))
                    held += 1
                    continue
                source, link = single_video(source), video_link(source, link)
            url = canonical_url(source, link)
            if self._listed(url, options):
                listed += 1
                continue
            self._add(url, source, options)
            added += 1
        if problems and len(problems) == len(links) and not any("://" in link for link in links):
            self.notice.emit("The copied text isn't a link. Copy the link from your browser's address bar.")
        elif problems:
            self.notice.emit(f"This link couldn't be added. {problems[0]}" if len(problems) == 1
                             else f"{len(problems)} links couldn't be added. {problems[0]}")
        elif listed:
            self.notice.emit("Already in the list with the same choices." if listed == 1
                             else f"{listed} links are already in the list with the same choices.")
        self._added_last = added
        if added:
            self._after_change()
        if held:
            self.playlistQuestion.emit(len(self._held))
        return added + listed + held

    def _listed(self, url: str, options: DownloadOptions) -> bool:
        """True when this link waits or downloads already with the same type and quality."""
        for job in self._context.store.jobs(ACTIVE_STATES):
            # A subscription's uploads carry its link but are not that whole channel or playlist.
            if job["url"] == url and not job["input_path"] and not job["batch"]:
                listed = DownloadOptions.from_dict(json.loads(job["options_json"]))
                if (listed.kind, listed.profile) == (options.kind, options.profile):
                    return True
        return False

    @Slot(str, "QVariantMap", result=int)
    def addLinksWith(self, text: str, options: dict[str, Any]) -> int:
        """Queue several links with the choices Download options made for all of them (Smart mode off);
        returns how many are now in the list or wait for the "video or playlist" answer."""
        try:
            chosen = DownloadOptions.from_dict({**base_options(load_settings(), str(options.get("kind"))).to_dict(),
                                                **options})
        except ValueError as error:
            self.notice.emit(str(error))
            return 0
        return self._queue_links(text, chosen)

    @Slot(str, "QVariantMap", "QVariantList", str, str, float, result=bool)
    def addJob(self, url: str, options: dict[str, Any], items: list[dict[str, Any]], title: str, thumbnail: str,
               not_before: float) -> bool:
        """Queue one analyzed link with its chosen options and items (from Download options)."""
        try:
            source = source_from_url(url)
            download_options = DownloadOptions.from_dict(
                {**base_options(load_settings(), str(options.get("kind"))).to_dict(), **options})
        except ValueError as error:
            self.notice.emit(str(error))
            return False
        link = canonical_url(source, url)
        if not items and self._listed(link, download_options):
            self.notice.emit("Already in the list with the same choices.")
            return True
        self._add(link, source, download_options, items, title, thumbnail, not_before)
        self._after_change()
        return True

    def add_subscription_items(self, entries: list[dict[str, Any]], source: Source, options: DownloadOptions,
                               subscription_id: int, account_id: int | None, not_before: float = 0.0,
                               title: str = "", url: str = "", folder: str = "") -> int:
        """Queue new uploads found by a subscription check (archived and filed under the subscription).

        `entries` hold each upload's id, title, url, and thumbnail. Several regular uploads become one
        download, titled `title`, whose videos list under it; one upload, or a premiere waiting for its
        start time (`not_before`), is a download of its own. `folder` names the folder outright (a
        playlist's uploads, one link each, carry no playlist name).
        """
        entries = [entry for entry in entries if str(entry.get("url") or "").startswith("https://")]
        if not entries:
            return 0
        state = "waiting_live" if not_before else ""
        if len(entries) == 1 or not_before:
            for entry in entries:
                # Filed under the subscription's link, so its archive and folders are the channel's.
                self._add(str(entry["url"]), source, options, title=str(entry.get("title") or ""),
                          thumbnail=str(entry.get("thumbnail") or ""), not_before=not_before,
                          subscription_id=subscription_id, account_id=account_id, state=state, folder=folder)
        else:
            items = [{"id": str(entry.get("id") or ""), "title": str(entry.get("title") or ""), "index": number,
                      "duration": entry.get("duration") or 0, "url": str(entry["url"]),
                      "thumbnail": str(entry.get("thumbnail") or "")} for number, entry in enumerate(entries, start=1)]
            name = f"{title or 'New uploads'}: {count_media(len(items), options.kind)}"
            self._add(url or str(entries[0]["url"]), source, options, items, name, items[0]["thumbnail"],
                      subscription_id=subscription_id, account_id=account_id, folder=folder, batch=True)
        self._after_change()
        return len(entries)

    def _add(self, url: str, source: Source, options: DownloadOptions, items: list[dict[str, Any]] | None = None,
             title: str = "", thumbnail: str = "", not_before: float = 0.0, subscription_id: int | None = None,
             account_id: int | None = None, state: str = "", input_path: str = "", folder: str = "",
             batch: bool = False) -> int:
        root = str(self._context.download_root(options.kind))
        job_id = self._context.store.add_job(
            url, source.kind, source.source_id, source.site, options.to_dict(), root, source.tab, title, thumbnail,
            items, account_id, subscription_id, state or ("scheduled" if not_before > time.time() else "queued"),
            not_before, input_path, folder, batch)
        # A removed job's id can be given out again: nothing of the old job may carry over.
        self._clear_scratch(job_id)
        return job_id

    @Slot(int, "QVariantMap")
    def extractJobAudio(self, job_id: int, choices: dict[str, Any]) -> None:
        """Extract the audio of every video a download saved, with the Extract audio dialog's choices."""
        videos = [record for record in self._context.store.history_for_job(job_id) if record["kind"] == "video"]
        self._extract(videos, choices)

    @Slot("QVariantList", "QVariantMap")
    def extractAudio(self, history_ids: list[int], choices: dict[str, Any]) -> None:
        """Extract the audio of library videos (songs among them are left out), with the dialog's choices."""
        records = [self._context.store.history_record(int(history_id)) for history_id in history_ids]
        videos = [record for record in records if record is not None and record["kind"] == "video"]
        if records and not videos:
            self.notice.emit("Only videos have audio to extract; these are songs already.")
            return
        self._extract(videos, choices)

    def _extract(self, records: list[dict[str, Any]], choices: dict[str, Any]) -> None:
        """Queue an audio extraction for each video file still there (one at a time per file).

        `choices` (format, bitrate, cover, tags, chapters, lyrics) go over the audio preferences;
        anything else in it is ignored.
        """
        present = [record for record in records if os.path.isfile(record["filepath"])]
        if not present:
            self.notice.emit("The video file is no longer there, so its audio can't be extracted.")
            return
        busy = {job["input_path"] for job in self._context.store.jobs(ACTIVE_STATES) if job["input_path"]}
        fresh = [record for record in present if record["filepath"] not in busy]
        if not fresh:
            self.notice.emit("Its audio is already being extracted.")
            return
        picked = {key: value for key, value in choices.items() if key in EXTRACT_CHOICES}
        try:
            options = DownloadOptions.from_dict({**base_options(load_settings()).to_dict(), **picked, "kind": "audio"})
        except ValueError as error:
            write_log(f"Audio choices can't be used: {error}", "critical")
            self.notice.emit("One of these audio choices isn't available. Pick another and try again.")
            return
        for record in fresh:
            path = record["filepath"]
            item_id = record["video_id"] or hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
            self._add(record["url"], Source("video", item_id, record["site"] or "generic"), options,
                      title=record["title"] or Path(path).stem, thumbnail=record["thumbnail"], input_path=path)
        songs = "The song appears" if len(fresh) == 1 else "The songs appear"
        self.notice.emit(f"Extracting the audio of {count_media(len(fresh), 'video')}. {songs} in Downloads and "
                         "the Library.")
        self._after_change()

    # ── Per-job actions ───────────────────────────────────────────────────

    @Slot(int)
    def pause(self, job_id: int) -> None:
        """Stop a download and keep its partial files for later."""
        if job_id in self._running:
            self._running[job_id].stop("pause")
        else:
            self._set_state(job_id, "paused", "")

    @Slot(int)
    def resume(self, job_id: int) -> None:
        """Put a paused, failed, or cancelled download back in the queue."""
        job = self._context.store.job(job_id)
        if job is None or job_id in self._running:
            return
        state = "scheduled" if job["not_before"] > time.time() else "queued"
        self._context.store.update_job(job_id, state=state, message="", error_key="", action="", attempts=0)
        # Videos that failed or stalled get their chance again; those that can't download stay skipped.
        self._context.store.reset_items(job_id, ("failed", "deferred"))
        self._after_change()

    @Slot(int, str)
    def moveToFolder(self, job_id: int, folder: str) -> None:
        """Save a download somewhere else (after a full disk or a refused folder) and resume it."""
        if job_id in self._running or not folder:
            return
        self._context.store.update_job(job_id, output_root=folder)
        self.resume(job_id)

    @Slot(int)
    def retry(self, job_id: int) -> None:
        """Try a failed download again (items skipped for good are tried again too).

        Videos downloaded before stay skipped: an earlier Download again doesn't carry over.
        """
        job = self._context.store.job(job_id)
        if job is None:
            return
        options = json.loads(job["options_json"])
        options["ignore_archive"] = False
        self._context.store.update_job(job_id, skip_ids_json="[]", options_json=json.dumps(options))
        self._context.store.reset_items(job_id, ("skipped",))
        self.resume(job_id)

    @Slot(int)
    def downloadAgain(self, job_id: int) -> None:
        """Download a finished download once more, even what the archive lists as downloaded before."""
        job = self._context.store.job(job_id)
        if job is None or job_id in self._running or job["input_path"]:
            return
        options = DownloadOptions.from_dict(json.loads(job["options_json"])).with_changes(ignore_archive=True)
        self._forget_session_archive(job_id)
        self._last_files.pop(job_id, None)
        self._context.store.update_job(job_id, options_json=json.dumps(options.to_dict()), skip_ids_json="[]")
        self._context.store.reset_items(job_id, ("done", "archived", "skipped"))
        self.resume(job_id)

    @Slot(int)
    def cancel(self, job_id: int) -> None:
        """Stop a download and delete its unfinished files (finished files stay)."""
        if job_id in self._running:
            self._running[job_id].stop("cancel")
            return
        job = self._context.store.job(job_id)
        if job is not None:
            self._remove_partials(job, set())
        self._set_state(job_id, "cancelled", "")

    @Slot(int, bool)
    def remove(self, job_id: int, delete_saved: bool) -> None:
        """Take a download off the list, stopping it and deleting its unfinished files.

        Its saved files stay (they are in the Library) unless `delete_saved` is set; then they go to
        the Recycle Bin with their captions, lyrics, and covers.
        """
        if job_id in self._running:
            self._running[job_id].stop("remove_files" if delete_saved else "remove")
            return
        job = self._context.store.job(job_id)
        if job is not None:
            self._remove_partials(job, set())
            if delete_saved and not self._recycle_saved(job):
                return
        self._forget_jobs([job_id])
        self._after_change()

    @Slot("QVariantList", result="QVariantMap")
    def removal(self, job_ids: list[int]) -> dict[str, Any]:
        """What removing these downloads would lose, so the page asks only when needed.

        `inProgress`: how many are downloading or still to (stopping them loses that work);
        `savedFiles`: the complete files they saved that are still there (offered for the Recycle Bin,
        never deleted unasked).
        """
        in_progress = saved = count = 0
        for job_id in (int(item) for item in job_ids):
            job = self._context.store.job(job_id)
            if job is None:
                continue
            count += 1
            in_progress += job_id in self._running or job["state"] in ACTIVE_STATES
            saved += sum(os.path.isfile(record["filepath"]) for record in self._context.store.history_for_job(job_id))
        return {"count": count, "inProgress": in_progress, "savedFiles": saved}

    @Slot(str, "QVariantList")
    def applyToJobs(self, action: str, job_ids: list[int]) -> None:
        """Pause, resume, try again, or remove several downloads ("remove_saved" also recycles saved files)."""
        handlers = {"pause": self.pause, "resume": self.resume, "retry": self.retry,
                    "remove": lambda job_id: self.remove(job_id, False),
                    "remove_saved": lambda job_id: self.remove(job_id, True)}
        handler = handlers.get(action)
        if handler is None:
            return
        with self._batch():
            for job_id in job_ids:
                handler(int(job_id))

    @contextmanager
    def _batch(self) -> Iterator[None]:
        """Refresh the list once, and say once what went to the Recycle Bin, for an action on many."""
        self._batching, self._batch_changed, self._batch_recycled = True, False, 0
        try:
            yield
        finally:
            self._batching = False
            if self._batch_recycled:
                self.notice.emit(f"Moved {_files(self._batch_recycled)} to the Recycle Bin.")
            if self._batch_changed:
                self._after_change()

    @Slot(int, int)
    def move(self, job_id: int, steps: int) -> None:
        """Move a download up or down the queue."""
        self._context.store.move_job(job_id, steps)
        self._after_change()

    def _forget_session_archive(self, job_id: int) -> None:
        """A Download again starts over: the videos an earlier one saved are fetched again too."""
        try:
            (self._context.job_dir(job_id) / SESSION_ARCHIVE).unlink(missing_ok=True)
        except OSError as error:
            write_log(f"The earlier Download again list of download {job_id} couldn't be removed: {error}", "critical")

    def _clear_run_folder(self) -> None:
        """Remove what runs left in the run folder when the app didn't end them itself (a crash, a
        power cut): sign-in cookie copies above all. Nothing runs yet, so all of it is stale."""
        root = self._context.run_root
        try:
            entries = list(root.iterdir()) if root.is_dir() else []
        except OSError as error:
            write_log(f"The run folder couldn't be read: {error}", "critical")
            return
        for entry in entries:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    for item in entry.rglob("*"):
                        if item.is_file() and not item.is_symlink():
                            wipe(item)  # cookie copies are overwritten before they go
                    shutil.rmtree(entry)
                else:
                    wipe(entry)
            except OSError as error:
                write_log(f"{entry.name} couldn't be removed from the run folder: {error}", "critical")

    def _clear_last_session(self) -> None:
        """Take finished and cancelled downloads off the list as the app closes (Preferences can keep them)."""
        if load_settings().get("downloads", {}).get("clear_finished_on_exit", True):
            self._forget_jobs([job["id"] for job in self._context.store.jobs(_CLEARABLE)])

    @Slot()
    def clearFinished(self) -> None:
        """Remove done and cancelled downloads from the list (failed ones stay to be tried again)."""
        self._forget_jobs([job["id"] for job in self._context.store.jobs(_CLEARABLE)])
        self._summary = ""
        self._after_change()

    @Slot(int, bool)
    def setExpanded(self, job_id: int, expanded: bool) -> None:
        """Show or hide a playlist's videos under it (for this session)."""
        self._expanded[job_id] = expanded
        self._sync_model()

    @Slot(int, result="QVariantList")
    def savedFiles(self, job_id: int) -> list[str]:
        """A playlist's saved (and earlier downloaded) files still on disk, in its order, for the players."""
        job = self._context.store.job(job_id)
        if job is None:
            return []
        items = self._context.store.job_items(job_id)
        saved = self._saved_files(job, items)
        ordered = [saved[item["item_id"]] for item in items if item["item_id"] in saved]
        return [path for path in ordered if os.path.isfile(path)]

    @Slot("QVariantList", result="QVariantMap")
    def pickedFlags(self, job_ids: list[int]) -> dict[str, bool]:
        """Which actions apply to any of these downloads: canPause, canResume, canRetry."""
        flags = {"canPause": False, "canResume": False, "canRetry": False}
        for job_id in (int(item) for item in job_ids):
            row = self._model.row_of(job_key(job_id))
            values = self._model.get(row) if row >= 0 else {}
            for name in flags:
                flags[name] = flags[name] or values.get(name) is True
        return flags

    # ── Queue-wide actions ────────────────────────────────────────────────

    @Slot()
    def pauseAll(self) -> None:
        """Pause the queue: running downloads stop and keep their partial files."""
        self._paused = True
        for running in list(self._running.values()):
            running.stop("pause_all")
        self._after_change()

    @Slot()
    def resumeAll(self) -> None:
        """Resume the queue and every paused download."""
        self._paused = False
        for job in self._context.store.jobs(("paused",)):
            self._context.store.update_job(job["id"], state="queued", message="")
        self._after_change()

    @Slot()
    def startNow(self) -> None:
        """Ignore the scheduled start time and start the queue now."""
        self._hold_until = 0.0
        settings = load_settings()
        if settings.get("schedule", {}).get("queue_start"):
            settings["schedule"]["queue_start"] = ""
            save_settings(settings)
        self._after_change()

    @Slot(str)
    def setWhenDone(self, action: str) -> None:
        """What to do once the queue is finished (this session)."""
        self._when_done = action
        self.changed.emit()

    @Slot()
    def performWhenDone(self) -> None:
        """Carry out the when-done action after its countdown."""
        action, self._when_done = self._when_done, "nothing"
        self.changed.emit()
        if action == "quit":
            self.quitRequested.emit()
        elif action in ("sleep", "hibernate", "shutdown") and not power.perform(action):
            what = {"sleep": "put the PC to sleep", "hibernate": "hibernate the PC", "shutdown": "shut down the PC"}
            self.notice.emit(f"Windows didn't let the app {what[action]}.")

    @Slot()
    def cancelWhenDone(self) -> None:
        """Keep the PC on: the countdown was cancelled."""
        self._when_done = "nothing"
        self.changed.emit()

    @Slot(str)
    def retry_after_tools(self) -> None:
        """The download tools were installed or updated: downloads that failed for them try again."""
        waiting = [job for job in self._context.store.jobs(("failed",))
                   if job["action"] in ("update_tools", "repair_tools")]
        for job in waiting:
            self._context.store.update_job(job["id"], state="queued", message="", action="", error_key="")
        if waiting:
            self.notice.emit("The download tools are up to date. Downloads that needed them are trying again.")
            self._after_change()

    def retrySignIn(self, site: str) -> None:
        """Queue again the downloads that stopped for a sign-in to this site."""
        for job in self._context.store.jobs(("needs_auth",)):
            if job["site"] == site:
                self._context.store.update_job(job["id"], state="queued", message="", action="", error_key="")
        self._after_change()

    def refresh_settings(self) -> None:
        """Preferences changed: re-read the start time and speed limits."""
        self._apply_schedule_settings()
        self._on_tick()

    # ── Running ───────────────────────────────────────────────────────────

    def _apply_schedule_settings(self) -> None:
        start = str(load_settings().get("schedule", {}).get("queue_start", ""))
        self._hold_until = next_queue_start(datetime.now(), start).timestamp() if start else 0.0

    def _concurrency(self) -> int:
        configured = int(load_settings().get("downloads", {}).get("concurrent", 0))
        return configured or DownloadDefaults.AUTO_CONCURRENT

    def _total_limit(self) -> int:
        network = load_settings().get("network", {})
        return limit_at(datetime.now(), int(network.get("limit_kib", 0)), network.get("limit_windows", []))

    def _job_archive(self, job: dict[str, Any]) -> str:
        if job["input_path"]:
            return f"extract:{job['input_path']}"  # one extraction of a file at a time; no archive
        options = DownloadOptions.from_dict(json.loads(job["options_json"]))
        return str(archive_path(Path(job["output_root"]), source_of(job), options.profile))

    def _pump(self) -> None:
        """Start queued jobs while there is room."""
        if self._paused or self._hold_until > time.time():
            return
        now = time.time()
        limit = self._concurrency()
        for job in self._context.store.jobs(_WAITING):
            if len(self._running) >= limit:
                break
            if job["not_before"] > now:
                continue
            site = self._context.site(job["site"])
            if not job["input_path"] and sum(1 for r in self._running.values() if r.site == job["site"]) >= site.max_concurrent:
                continue
            archive = self._job_archive(job)
            if any(r.archive == archive for r in self._running.values()):
                continue
            self._start(job, archive)

    def _start(self, job: dict[str, Any], archive: str) -> None:
        options = DownloadOptions.from_dict(json.loads(job["options_json"]))
        settings = load_settings()
        downloads = settings.get("downloads", {})
        total = self._total_limit()
        self._applied_limit = total
        live = options.live_from_start or options.wait_for_video or job["state"] == "waiting_live"
        fragments = int(downloads.get("fragments", 0)) or DownloadDefaults.AUTO_FRAGMENTS
        rate = 0 if live else per_job_limit(total, len(self._running) + 1)
        options = with_network(options, settings).with_changes(limit_rate=rate, fragments=1 if rate else fragments)
        running = _Running(job["id"], archive, "" if job["input_path"] else job["site"], live, job["output_root"])
        self._running[job["id"]] = running
        self._worked = True
        self._context.store.update_job(job["id"], state="running", message="", error_key="", action="")
        skip = tuple(json.loads(job["skip_ids_json"] or "[]"))
        spec_args = (job, options, skip, int(downloads.get("max_attempts", 0)),
                     int(downloads.get("retry_delay", DownloadDefaults.RETRY_DELAY)))
        self._runner.start(self._work, running, spec_args,
                           on_done=lambda result, r=running: self._finished(r, result),
                           on_error=lambda message, r=running: self._crashed(r, message))
        if not self._poll.isActive():
            self._poll.start()
        self.busyChanged.emit()

    def _work(self, running: _Running, spec_args: tuple[Any, ...]) -> JobResult:
        """On the pool: hand out the sign-in, run the download, take the sign-in back."""
        job, options, skip, max_attempts, retry_delay = spec_args
        if job["input_path"]:
            return self._extract_audio(running, job, options)
        context = self._context
        source = source_of(job)
        account = context.account_for(job["site"], job["account_id"])
        auth: Auth | None = context.browser_auth(account)
        checkout: Checkout | None = None
        if account is not None and account["method"] in VAULT_METHODS and context.vault.exists(account["id"]):
            try:
                checkout = context.vault.checkout(account["id"], context.site(job["site"]),
                                                  context.run_root / f"{job['id']}-{int(time.time())}")
                auth = Auth(cookies_file=str(checkout.path))
            except (SecretError, OSError, TimeoutError) as error:
                write_log(f"Sign-in for {job['site']} couldn't be used: {error}", "critical")
                context.store.update_account(account["id"], status="expired")
        try:
            root = Path(job["output_root"])
            paths = RunPaths(root, Path(running.archive), context.job_dir(job["id"]), context.cache_dir)
            urls = tuple(str(item["url"]) for item in context.store.job_items(job["id"]) if item["url"]) \
                if job["batch"] else ()
            spec = JobSpec(job["url"], source, options, paths, auth, max_attempts, retry_delay, skip, urls,
                           job["folder"])

            def saved(info: dict[str, Any], path: Path) -> None:
                with running.lock:
                    running.files.append((info, str(path)))

            def noted(event: Event) -> None:
                if event.kind == "error":  # yt-dlp's own words, for the log; the row shows the plain one
                    write_log(f"Download {job['id']}: {event.text}", "critical")

            executor = JobExecutor(spec, context.tools, on_file=saved, on_event=noted,
                                   update_tools=self._tools.update_ytdlp, stall_seconds=self._stall_seconds,
                                   runner=self._program_runner, lyrics_fetch=self._lyrics_fetch)
            running.executor = executor
            if running.stop_reason:
                return JobResult("stopped")
            return executor.run()
        finally:
            if checkout is not None and account is not None:
                try:
                    context.vault.checkin(account["id"], checkout)
                except (SecretError, OSError, TimeoutError) as error:
                    write_log(f"Sign-in cookies couldn't be stored back: {error}", "critical")

    def _extract_audio(self, running: _Running, job: dict[str, Any], options: DownloadOptions) -> JobResult:
        """On the pool: write a downloaded video's audio into the audio folder."""
        context = self._context
        video = Path(job["input_path"])
        record = context.store.history_for_path(job["input_path"]) or {}
        cover = cache_file(context.thumbnails_dir, job["thumbnail"]) if job["thumbnail"].startswith("https://") else None
        spec = ExtractSpec(video, options, Path(job["output_root"]), self._mirror_folder(video, record),
                           context.job_dir(job["id"]), item_id=job["source_id"], title=job["title"],
                           uploader=str(record.get("uploader") or ""), url=job["url"], thumbnail=job["thumbnail"],
                           cover_hint=cover)

        def saved(info: dict[str, Any], path: Path) -> None:
            with running.lock:
                running.files.append((info, str(path)))

        extractor = AudioExtractor(spec, context.tools, on_file=saved, runner=self._program_runner,
                                   lyrics_fetch=self._lyrics_fetch)
        running.executor = extractor
        if running.stop_reason:
            return JobResult("stopped")
        return extractor.run()

    def _mirror_folder(self, video: Path, record: dict[str, Any]) -> str:
        """The video's folder below its download root (a playlist's, or "" for the root), which the audio mirrors."""
        root = self._context.roots_of([{**record, "filepath": str(video)}])[0]
        if root is None:
            return ""  # a video saved elsewhere: its audio goes straight into the audio folder
        folder = video.parent.relative_to(root)
        return "" if folder == Path(".") else folder.as_posix()

    def _take_updates(self, running: _Running) -> bool:
        """Store what the download learned about its videos (its list, skips, stalls); True when any changed."""
        executor = running.executor
        if not isinstance(executor, JobExecutor):
            return False
        updates = executor.take_updates()
        job = self._context.store.job(running.job_id)
        if job is None or not source_of(job).is_collection:
            return False  # one video: its row says how it went
        store = self._context.store
        changed = False
        states: list[tuple[str, str, str]] = []
        for kind, value in updates:
            if kind == "listed":
                store.add_items(running.job_id, value)
                if not job["thumbnail"] and value and value[0].get("thumbnail"):
                    # A playlist without its own picture shows its first video's.
                    store.update_job(running.job_id, thumbnail=str(value[0]["thumbnail"]))
                    job = store.job(running.job_id) or job
                changed = True
            elif kind == "dropped":
                store.drop_item(running.job_id, str(value))
                changed = True
            elif kind == "titled":
                # A list that named no titles: the video's own, as it starts (only fills a blank or a guess).
                item_id, title = value
                store.retitle_item(running.job_id, str(item_id), str(title))
                changed = True
            elif kind == "list_title" and not job["title"]:
                store.update_job(running.job_id, title=str(value))
                changed = True
            elif kind == "state":
                states.append(value)
        if states:
            store.set_item_states(running.job_id, states)
            changed = True
        return changed

    def _drain_files(self, running: _Running) -> bool:
        """Record finished files in the library (on the GUI thread); True when there were any."""
        with running.lock:
            files, running.files = running.files, []
        job = self._context.store.job(running.job_id)
        if job is not None and files and not job["title"]:
            # A quick download can finish before the progress poll saw its title.
            info = files[0][0]
            collection = source_of(job).is_collection
            title = str((info.get("playlist_title") if collection else "") or info.get("title") or "")
            thumbnail = job["thumbnail"] or str(info.get("thumbnail") or "")
            if title:
                self._context.store.update_job(running.job_id, title=title, thumbnail=thumbnail)
                job = self._context.store.job(running.job_id)
        for info, path in files:
            try:
                size = Path(path).stat().st_size
            except OSError:
                size = 0
            extension = Path(path).suffix[1:].lower()
            height, duration = info.get("height"), info.get("duration")
            group_key, group_title = group_of(Path(path), Path(job["output_root"]) if job else None)
            position = info.get("playlist_index")
            history_id = self._context.store.add_history(
                path, job_id=running.job_id, video_id=str(info.get("id") or ""),
                site=job["site"] if job else "", kind="audio" if extension in AUDIO_EXTENSIONS else "video",
                title=str(info.get("title") or Path(path).stem),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                url=str(info.get("webpage_url") or ""),
                height=height if isinstance(height, int) else 0,
                duration=float(duration) if isinstance(duration, (int, float)) else 0.0,
                size=size, thumbnail=str(info.get("thumbnail") or (job or {}).get("thumbnail", "")),
                group_key=group_key, group_title=group_title,
                position=position if isinstance(position, int) else 0,
                output_root=job["output_root"] if job else "")
            if job is not None and info.get("id") and source_of(job).is_collection:
                # A video the list didn't name (a site without a playlist file) is added as it is saved.
                self._context.store.add_items(running.job_id, [{
                    "id": str(info["id"]), "title": str(info.get("title") or ""),
                    "url": str(info.get("webpage_url") or ""), "thumbnail": str(info.get("thumbnail") or "")}])
                self._context.store.set_item_state(running.job_id, str(info["id"]), "done")
            self._last_files[running.job_id] = path
            self.fileSaved.emit(history_id, path)
        return bool(files)

    def _finished(self, running: _Running, result: JobResult) -> None:
        self._drain_files(running)
        self._take_updates(running)
        self._current.pop(running.job_id, None)
        self._numbers.pop(running.job_id, None)
        self._running.pop(running.job_id, None)
        self._snapshots.pop(running.job_id, None)
        self._settle(running, result)
        self.busyChanged.emit()
        self._after_change()
        self._check_finished_queue()

    def _settle(self, running: _Running, result: JobResult | None) -> None:
        """Put a download that ended in the state its stop reason asks for, or record its result.
        `result` is None for a download the app leaves running as it quits."""
        job = self._context.store.job(running.job_id)
        reason = running.stop_reason
        partials = running.executor.partial_files() if running.executor is not None else set()
        if job is None:
            self._forget_jobs([running.job_id])
        elif reason in ("remove", "remove_files"):
            self._remove_partials(job, partials)
            if reason == "remove" or self._recycle_saved(job):
                self._forget_jobs([running.job_id])
            else:
                self._set_state(running.job_id, "cancelled", "", refresh=False)
        elif reason == "cancel":
            self._remove_partials(job, partials)
            self._set_state(running.job_id, "cancelled", "", refresh=False)
        else:
            self._keep_partials(running.job_id, partials)
            if reason in ("pause", "pause_all"):
                self._set_state(running.job_id, "paused", "", refresh=False)
            elif reason in ("restart", "shutdown") or result is None:
                self._set_state(running.job_id, "queued", "", refresh=False)
            else:
                self._record_result(job, result)
                if result.state == "done":
                    self._tidy_partials(job)
                    self._tidy_scratch(job["output_root"])

    def _record_result(self, job: dict[str, Any], result: JobResult) -> None:
        job_id = job["id"]
        failure = result.failure
        self._mark_downloaded_before(job)
        if result.state == "done" and not result.files and result.archived == 1 and not result.skipped \
                and not job["batch"]:
            self._record_archived(job, result)
            return
        skip_ids = sorted({f.item_id for f in result.skipped if f.item_id} | set(json.loads(job["skip_ids_json"])))
        for skipped in result.skipped:
            self._context.store.set_item_state(job_id, skipped.item_id, "skipped", skipped.category.final)
        title = job["title"] or (result.files[0].stem if result.files else "")
        state = {"done": "done", "needs_auth": "needs_auth", "disk_full": "paused"}.get(result.state, "failed")
        message = result.message
        if result.rename_errors:
            write_log("File names left as they were: " + "; ".join(result.rename_errors), "general")
            message += f" ({_files(len(result.rename_errors))} kept the names the site gave)"
        self._context.store.update_job(
            job_id, state=state, message=message, error_key=failure.category.key if failure else "",
            action=failure.category.action if failure and state != "done" else "", files_done=len(result.files),
            skip_ids_json=json.dumps(skip_ids), attempts=result.attempts, title=title,
            finished=time.time() if state in ("done", "failed") else None)
        name = title or job["url"]
        self._summary = f"{name}: {message}"
        settings = load_settings()
        notify = bool(settings.get("notifications", {}).get("enabled", True))
        if state == "done" and notify:
            self._notifier.notify("Audio extracted" if job["input_path"] else "Download finished", f"{name}\n{message}",
                                  str(result.files[-1]) if result.files else "")
        elif state == "needs_auth":
            self.signInNeeded.emit(job["site"])
            if notify:
                self._notifier.notify("Sign-in needed", f"{name}\n{message}")
        elif result.state == "disk_full":
            self._paused = True
            self.notice.emit("The drive is full, so downloads are paused. Free up space or choose another folder, "
                             "then click Resume all.")
            if notify:
                self._notifier.notify("Downloads paused", "The drive is full. Free up space, then resume.")
        elif state == "failed" and notify:
            self._notifier.notify("Download failed", f"{name}\n{message}")

    def _keep_partials(self, job_id: int, partials: set[str]) -> None:
        """Remember a stopped download's unfinished files, with any kept from its earlier runs."""
        known = self._saved_partials(job_id)
        if partials and not partials <= known:
            self._note_partials(job_id, known | partials)

    def _note_partials(self, job_id: int, partials: set[str]) -> None:
        """Write which unfinished files a download keeps for later; with none, the note goes."""
        target = self._context.job_dir(job_id) / PARTIALS_FILE
        try:
            if partials:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(sorted(partials)), encoding="utf-8")
            else:
                target.unlink(missing_ok=True)
        except OSError as error:
            write_log(f"Unfinished files of download {job_id} couldn't be noted: {error}", "general")

    def _tidy_partials(self, job: dict[str, Any]) -> None:
        """A finished download keeps only the unfinished files of the videos it couldn't download, which
        Try again continues; the rest, such as a saved video's leftover from an attempt that picked
        another stream, are deleted."""
        noted = self._saved_partials(job["id"])
        if not noted or self._shares_archive(job):
            return
        open_tags = [f"[{item['item_id']}]" for item in self._context.store.job_items(job["id"])
                     if item["state"] in ("skipped", "failed")]
        kept = {path for path in noted if any(tag in Path(path).name for tag in open_tags)}
        self._note_partials(job["id"], kept)
        remove_partials(noted - kept, Path(job["output_root"]) / ".incomplete")

    def _shares_archive(self, job: dict[str, Any]) -> bool:
        """True while another download of the same videos runs (it may be continuing the same files)."""
        archive = self._job_archive(job)
        return any(r.archive == archive and r.job_id != job["id"] for r in self._running.values())

    def _saved_partials(self, job_id: int) -> set[str]:
        try:
            saved = json.loads((self._context.job_dir(job_id) / PARTIALS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {item for item in saved if isinstance(item, str)} if isinstance(saved, list) else set()

    def _remove_partials(self, job: dict[str, Any], partials: set[str]) -> None:
        """Delete a download's unfinished files: those reported now and those noted when it stopped before."""
        saved = self._saved_partials(job["id"])
        if saved and self._shares_archive(job):
            saved = set()
        else:
            self._note_partials(job["id"], set())
        remove_partials(partials | saved, Path(job["output_root"]) / ".incomplete")
        self._tidy_scratch(job["output_root"])

    def _tidy_scratch(self, root: str) -> None:
        """Remove the empty folders yt-dlp left in a download folder's unfinished-file folder.

        Not while another download into that folder runs: it may have made its folder there and not
        yet written into it.
        """
        if any(os.path.normcase(running.root) == os.path.normcase(root) for running in self._running.values()):
            return
        try:
            remove_empty_scratch(Path(root) / ".incomplete")
        except OSError as error:
            write_log(f"Empty folders in {root} couldn't be removed: {error}", "general")

    def release_files(self, paths: list[str], wait_seconds: float = 3.0) -> None:
        """Make the app let go of files about to be deleted: stop audio extractions reading them, then
        the built-in players (see PlayerController.release_files).

        A stopped extraction's FFmpeg holds the video until its process ends, so this waits for those
        jobs to settle, for at most `wait_seconds`; only queued events run meanwhile, never a click.
        """
        wanted = {os.path.normcase(os.path.abspath(path)) for path in paths}
        stopping = [running.job_id for running in self._running.values()
                    if (job := self._context.store.job(running.job_id)) is not None and job["input_path"]
                    and os.path.normcase(os.path.abspath(job["input_path"])) in wanted]
        for job_id in stopping:
            self.cancel(job_id)
        deadline = time.monotonic() + wait_seconds
        while any(job_id in self._running for job_id in stopping) and time.monotonic() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 50)
        self._release_player(paths)

    def _recycle_saved(self, job: dict[str, Any]) -> bool:
        """Move a download's saved files to the Recycle Bin and take them out of the Library; its
        playlist's or channel's folder goes too once it is empty.

        False when Windows couldn't move some of them (a file open in another program): those stay in
        the Library, the notice names them, and the download stays listed.
        """
        records = self._context.store.history_for_job(job["id"])
        paths = [str(record["filepath"]) for record in records]
        saved = [path for path in paths if os.path.isfile(path)]
        self.release_files(saved)
        failed = set(recycle_saved(list(zip(paths, self._context.roots_of(records)))))
        self._context.store.delete_history(record["id"] for record in records if record["filepath"] not in failed)
        if len(failed) < len(records):
            self.filesRemoved.emit()
        moved = len(saved) - len(failed)
        if moved and self._batching:
            self._batch_recycled += moved
        elif moved and not failed:
            self.notice.emit(f"Moved {_files(moved)} to the Recycle Bin.")
        if failed:
            self.notice.emit(failure_notice(sorted(failed)))
        return not failed

    def _forget_jobs(self, job_ids: list[int]) -> None:
        """Delete jobs with their scratch folders and the unfinished files they kept."""
        for job_id in job_ids:
            job = self._context.store.job(job_id)
            if job is not None:
                self._remove_partials(job, set())
        self._context.store.delete_jobs(job_ids)
        for job_id in job_ids:
            self._clear_scratch(job_id)

    def _clear_scratch(self, job_id: int) -> None:
        """Forget what this app kept about a job id: its scratch folder (journal, unfinished files) and Play file."""
        self._last_files.pop(job_id, None)
        shutil.rmtree(self._context.job_dir(job_id), ignore_errors=True)

    def _mark_downloaded_before(self, job: dict[str, Any]) -> None:
        """A list's videos still waiting as its download ends, which its archive records (saved by an
        earlier run, or listed before the site changed the list), show as downloaded before."""
        if job["input_path"] or not job["items_total"]:
            return
        archived = read_archive_ids(Path(self._job_archive(job)))
        waiting = [(str(item["item_id"]), "archived", "") for item in self._context.store.job_items(job["id"])
                   if item["state"] == "pending" and item["item_id"] in archived]
        if waiting:
            self._context.store.set_item_states(job["id"], waiting)

    def _record_archived(self, job: dict[str, Any], result: JobResult) -> None:
        """One video the archive skipped and nothing else.

        While its file is still on disk, the job shows it as downloaded and Play opens that file. When
        the file is gone (deleted, or never in this library), asking for the video again means wanting
        it again, so the job downloads it once more past the archive.
        """
        existing = self._existing_file(job, result.archived_ids)
        options = DownloadOptions.from_dict(json.loads(job["options_json"]))
        if existing is None and not options.ignore_archive:
            self._forget_session_archive(job["id"])
            self._context.store.update_job(
                job["id"], options_json=json.dumps(options.with_changes(ignore_archive=True).to_dict()),
                state="queued", message="", error_key="", action="", attempts=0)
            return
        message = "Already downloaded"
        fields: dict[str, Any] = {"state": "done", "message": message, "error_key": "", "action": "",
                                  "files_done": 0, "attempts": result.attempts, "finished": time.time()}
        if existing:
            self._last_files[job["id"]] = existing["filepath"]
            fields["title"] = job["title"] or existing["title"]
            fields["thumbnail"] = job["thumbnail"] or existing["thumbnail"]
        self._context.store.update_job(job["id"], **fields)
        self._summary = f"{fields.get('title') or job['title'] or job['url']}: {message}"

    def _existing_file(self, job: dict[str, Any], ids: list[str]) -> dict[str, Any] | None:
        """The library's newest file of this job's video, of the same type, that is still on disk.

        One in the file type asked for (an MKV, not the MP4 of the same video) comes first.
        """
        options = DownloadOptions.from_dict(json.loads(job["options_json"]))
        present = [record for record in self._context.store.history_of_video(job["site"], [*ids, job["source_id"]],
                                                                             job["url"])
                   if record["kind"] == options.kind and os.path.isfile(record["filepath"])]
        wanted = f".{options.extension}" if options.extension else ""
        return next((record for record in present if wanted and record["filepath"].lower().endswith(wanted)),
                    present[0] if present else None)

    def _crashed(self, running: _Running, message: str) -> None:
        """The worker raised (a bug): record it instead of leaving the job running forever."""
        self._drain_files(running)
        self._take_updates(running)
        self._current.pop(running.job_id, None)
        self._numbers.pop(running.job_id, None)
        self._running.pop(running.job_id, None)
        self._snapshots.pop(running.job_id, None)
        write_log(f"Download {running.job_id} stopped unexpectedly: {message}", "critical")
        self._set_state(running.job_id, "failed", "Something went wrong inside the app. Try again; if it happens "
                        "again, turn on logs in Preferences and report it.", refresh=False)
        self.busyChanged.emit()
        self._after_change()

    def _set_state(self, job_id: int, state: str, message: str, refresh: bool = True) -> None:
        if self._context.store.job(job_id) is None:
            return
        self._context.store.update_job(job_id, state=state, message=message)
        if refresh:
            self._after_change()

    def _check_finished_queue(self) -> None:
        """Run the when-done action once nothing is left to do: not while the queue or a download is
        paused (Pause all, a full drive), only when every download has finished."""
        if self._running or not self._worked or self._paused:
            return
        if self._context.store.jobs(_WAITING + ("retry_wait", "paused")):
            return
        self._worked = False
        if self._when_done != "nothing":
            self.whenDoneCountdown.emit(self._when_done)

    # ── Timers ────────────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        """Every few seconds: start scheduled jobs and follow speed-limit windows."""
        if self._hold_until and self._hold_until <= time.time():
            self.startNow()
            return
        now = time.time()
        for job in self._context.store.jobs(("scheduled",)):
            if job["not_before"] <= now:
                self._context.store.update_job(job["id"], state="queued")
        total = self._total_limit()
        if total != self._applied_limit and any(not r.live for r in self._running.values()):
            # A speed-limit window began or ended: restart downloads so they take the new limit
            # (they continue from their partial files).
            for running in self._running.values():
                if not running.live:
                    running.stop("restart")
        self._applied_limit = total
        self._after_change()

    def _refresh_running(self) -> None:
        """Copy running jobs' progress into the list, totals, and taskbar."""
        if not self._running:
            self._poll.stop()
            self._speed, self._progress = 0.0, 0.0
            waiting = self._paused and bool(self._context.store.jobs(_WAITING))
            self._taskbar.update(0.0 if waiting else None, PAUSED)
            self._keep_awake(False)
            self.changed.emit()
            return
        speeds, fractions = 0.0, []
        relist = False
        for job_id, running in list(self._running.items()):
            relist |= self._drain_files(running)
            if running.executor is None:
                continue
            relist |= self._take_updates(running)
            snap = running.executor.snapshot()
            self._snapshots[job_id] = snap
            speeds += snap.speed
            job = self._context.store.job(job_id)
            if job is None:
                continue
            # A playlist is named after itself, never after the video it is on.
            title = snap.playlist_title if source_of(job).is_collection else snap.title
            if not job["title"] and title:
                self._context.store.update_job(job_id, title=title, thumbnail=job["thumbnail"] or snap.thumbnail)
                job = self._context.store.job(job_id) or job
                relist = True
            if self._current.get(job_id) != snap.item_id:
                # The list moved on to another video: the one before shows how it ended.
                self._current[job_id] = snap.item_id
                relist = True
            if relist:
                continue  # the whole list is rebuilt below
            total = int(job["items_total"] or 0) if job["items_total"] > 1 else 0
            counts = self._context.store.item_counts(job_id) if total else {}
            values = self._live_values(job, snap, counts, self._item_number(job_id, snap.item_id) if total else 0)
            fractions.append(max(values["progress"], 0.0))
            self._model.update(job_key(job_id), values)
            if total and snap.item_id and self._model.row_of(entry_key(job_id, snap.item_id)) >= 0:
                self._model.update(entry_key(job_id, snap.item_id), running_values(snap))
        if relist:
            self._sync_model()
            fractions = [max(float(self._model.get(self._model.row_of(job_key(job_id))).get("progress", 0.0)), 0.0)
                         for job_id in self._running if self._model.row_of(job_key(job_id)) >= 0]
        self._speed = speeds
        self._progress = sum(fractions) / len(fractions) if fractions else 0.0
        self._taskbar.update(self._progress if fractions else 0.0, NORMAL if fractions else INDETERMINATE)
        self._keep_awake(True)
        self.changed.emit()

    def _keep_awake(self, on: bool) -> None:
        wanted = on and bool(load_settings().get("downloads", {}).get("keep_awake", True))
        if wanted != self._awake:
            power.keep_awake(wanted)
            self._awake = wanted

    def _after_change(self) -> None:
        if self._batching:
            self._batch_changed = True
            return
        self._pump()
        self._sync_model()
        self.changed.emit()

    def _sync_model(self) -> None:
        rows: list[dict[str, Any]] = []
        for job in self._context.store.jobs():
            rows += self._rows_of(job)
        self._model.sync(rows)

    def _rows_of(self, job: dict[str, Any]) -> list[dict[str, Any]]:
        """A download's row, with its live progress, and its videos' rows when it is a playlist shown open."""
        store = self._context.store
        job_id = job["id"]
        if job["state"] == "done" and job_id not in self._last_files:
            last = store.last_file(job_id)
            if not last and not job["files_done"]:
                # "Already downloaded": its Play button plays the file the library has.
                existing = self._existing_file(job, [])
                last = existing["filepath"] if existing else ""
            self._last_files[job_id] = last
        options = json.loads(job["options_json"])
        kind = kind_of(options)
        # A list of one is shown as that one video.
        total = int(job["items_total"] or 0) if job["items_total"] > 1 else 0
        counts = store.item_counts(job_id) if total else {}
        expanded = self._expanded.get(job_id, total <= OPEN_UP_TO)
        row = job_row(job, self._context.site(job["site"]).label, self._last_files.get(job_id, ""), counts, expanded,
                      options.get("kind", "video"))
        snap = self._snapshots.get(job_id) if job_id in self._running else None
        items = store.job_items(job_id) if total and row["expanded"] else []
        if snap is not None:
            self._numbers.pop(job_id, None)  # the list may have changed: count again
            row.update(self._live_values(job, snap, counts, self._item_number(job_id, snap.item_id) if total else 0))
        rows = [row]
        if row["expanded"]:
            saved = self._saved_files(job, items)
            noun_kind = "audio" if kind == "audio" else "video"
            rows += [entry_row(job, item, number, noun_kind, saved.get(item["item_id"], ""), snap)
                     for number, item in enumerate(items, start=1)]
        return rows

    def _item_number(self, job_id: int, item_id: str) -> int:
        """Where the video now downloading is in its playlist, asked of the store once per video."""
        cached = self._numbers.get(job_id)
        if cached is None or cached[0] != item_id:
            cached = (item_id, self._context.store.item_number(job_id, item_id) if item_id else 0)
            self._numbers[job_id] = cached
        return cached[1]

    def _live_values(self, job: dict[str, Any], snap: Snapshot, counts: dict[str, int],
                     number: int) -> dict[str, Any]:
        """A running download's row values: one video's progress, or a playlist's steady overall progress
        (`number` is the current video's place in the list)."""
        total = int(job["items_total"] or 0)
        if total <= 1:
            values = running_values(snap)
            values["itemText"] = ""
            return values
        kind = json.loads(job["options_json"]).get("kind", "video")
        return collection_values(snap, counts, total, kind, number)

    def _saved_files(self, job: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, str]:
        """The file each saved (or earlier downloaded) video of a playlist is in, by video ID, for Play."""
        store = self._context.store
        saved = {str(record["video_id"]): str(record["filepath"]) for record in store.history_for_job(job["id"])
                 if record["video_id"]}
        earlier = [item["item_id"] for item in items if item["state"] == "archived" and item["item_id"] not in saved]
        if earlier:
            kind = DownloadOptions.from_dict(json.loads(job["options_json"])).kind
            for record in store.history_of_video(job["site"], earlier, ""):
                if record["kind"] == kind and str(record["video_id"]) not in saved:
                    saved[str(record["video_id"])] = str(record["filepath"])
        return saved

    # ── Lifetime ──────────────────────────────────────────────────────────

    def attach_window(self, hwnd: int) -> None:
        """Show overall progress on this window's taskbar button."""
        self._taskbar.attach(hwnd)

    def shutdown(self) -> None:
        """Stop running downloads; they resume next time the app starts."""
        self._poll.stop()
        self._tick.stop()
        for running in list(self._running.values()):
            running.stop("shutdown")
        self._runner.shutdown(10_000)
        for running in list(self._running.values()):
            self._drain_files(running)
            self._take_updates(running)
            self._settle(running, None)  # paused stays paused, cancelled and removed go; the rest resumes
        self._running.clear()
        self._clear_last_session()
        self._keep_awake(False)
        self._taskbar.close()


def _files(count: int) -> str:
    """A count of files: "1 file", "3 files"."""
    return f"{count} file{'s' if count != 1 else ''}"
