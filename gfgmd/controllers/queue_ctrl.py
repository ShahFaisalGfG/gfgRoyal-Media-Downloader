# queue_ctrl.py - the download queue: adding, running, pausing, retrying, and finishing jobs
#
# Jobs live in library.db, so the queue survives restarts and crashes. Each running job is a
# JobExecutor on the task pool; a 4 Hz timer copies its progress into the list model, totals, and
# the taskbar. The pump starts queued jobs while there is room: within the concurrency limit, the
# site's own limit, after any scheduled start time, and never two jobs sharing one archive.

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from gfgmd.config.defaults import DownloadDefaults, FormatDefaults, PresetDefaults
from gfgmd.core.archive import archive_path
from gfgmd.core.auth import Checkout
from gfgmd.core.command import Auth, RunPaths
from gfgmd.core.extract import AudioExtractor, ExtractSpec
from gfgmd.core.jobs import JobExecutor, JobResult, JobSpec, Runner
from gfgmd.core.lyrics import Fetch
from gfgmd.core.naming import AUDIO_EXTENSIONS, remove_partials
from gfgmd.core.options import DownloadOptions, options_from_preset
from gfgmd.core.progress import Snapshot
from gfgmd.core.runner import run_to_completion
from gfgmd.core.schedule import limit_at, next_queue_start, per_job_limit
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sources import Source, canonical_url, source_from_url
from gfgmd.core.store import ACTIVE_STATES
from gfgmd.models.list_model import DictListModel
from gfgmd.services import power
from gfgmd.services.context import VAULT_METHODS, AppContext
from gfgmd.services.notifier import Notifier
from gfgmd.services.recycle import recycle_media
from gfgmd.services.taskbar import INDETERMINATE, NORMAL, PAUSED, TaskbarProgress
from gfgmd.services.tasks import TaskRunner
from gfgmd.services.thumbnails import cache_file
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.format import format_bytes, format_duration
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings, save_settings

POLL_MS = 250
TICK_MS = 15_000
ROLES = ("jobId", "title", "url", "site", "kind", "thumbnail", "jobState", "statusText", "stage", "progress",
         "detail", "itemText", "message", "action", "folder", "lastFile", "canPause", "canResume", "canRetry",
         "canRedownload", "hasItems")
_WAITING = ("queued", "scheduled", "waiting_live")
_LIVE_STATES = ("running", "retry_wait")
_CLEARABLE = ("done", "cancelled")
# What the Extract audio dialog chooses, over the audio preferences.
EXTRACT_CHOICES = ("audio_format", "audio_quality", "cover", "lyrics", "lyrics_online", "embed_thumbnail",
                   "embed_metadata", "embed_chapters")
# Unfinished files a stopped download reported, kept in its scratch folder so Cancel and Remove can
# delete them after a pause or a restart, when no download is running to report them.
PARTIALS_FILE = "partials.json"


@dataclass
class _Running:
    """A job on the pool: its executor once built, why it is being stopped, and its saved files."""

    job_id: int
    archive: str
    site: str  # "" for an audio extraction, which no site limits
    live: bool
    executor: JobExecutor | AudioExtractor | None = None
    stop_reason: str = ""
    files: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def stop(self, reason: str) -> None:
        self.stop_reason = reason
        if self.executor is not None:
            self.executor.stop()


def base_options(settings: dict[str, Any]) -> DownloadOptions:
    """The format choices in Preferences, as download options."""
    formats = settings.get("formats", {})
    downloads = settings.get("downloads", {})
    container = formats.get("container", "mp4")
    langs = [code for code in formats.get("audio_langs", []) if isinstance(code, str)]
    # Extra audio tracks need languages and an MP4 or MKV file; otherwise the original track alone.
    tracks = formats.get("audio_tracks", "original")
    if tracks != "original" and (not langs or container not in ("mp4", "mkv")):
        tracks, langs = "original", []
    return DownloadOptions.from_dict({
        "container": container,
        "codec_profile": formats.get("codec_profile", "compatible"),
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
        "embed_thumbnail": formats.get("embed_thumbnail", True),
        "embed_metadata": formats.get("embed_metadata", True),
        "embed_chapters": formats.get("embed_chapters", True),
        "sponsorblock": formats.get("sponsorblock", "off"),
        "sponsorblock_categories": formats.get("sponsorblock_categories", ["sponsor"]),
        "filename_style": downloads.get("filename_style", "title-quality"),
    })


def source_of(job: dict[str, Any]) -> Source:
    """The Source a stored job was classified as."""
    return Source(job["source_kind"], job["source_id"], job["site"], job["tab"])


class QueueController(QObject):
    """The download queue for QML."""

    changed = Signal()
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

    def __init__(self, context: AppContext, tools: ToolManager, notifier: Notifier,
                 parent: QObject | None = None, runner: Runner = run_to_completion,
                 lyrics_fetch: Fetch | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._tools = tools
        self._notifier = notifier
        self._program_runner = runner
        # The app passes lyrics.fetch_json; tests leave it out, so they never reach LRCLIB.
        self._lyrics_fetch = lyrics_fetch
        self._model = DictListModel(ROLES, "jobId", self)
        self._runner = TaskRunner(DownloadDefaults.MAX_CONCURRENT + 2, self)
        self._running: dict[int, _Running] = {}
        self._snapshots: dict[int, Snapshot] = {}
        # Each download's newest saved file (for its Play button), read from the library once per job.
        self._last_files: dict[int, str] = {}
        self._paused = False
        self._hold_until = 0.0
        self._applied_limit = 0
        self._when_done = "nothing"
        self._worked = False
        self._speed = 0.0
        self._progress = 0.0
        self._summary = ""
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
        # Also here, not only on closing: a crash or a power cut skips the clean-up there.
        self._clear_last_session()
        self._apply_schedule_settings()
        self._sync_model()
        self._tick.start()

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

    def _preset_options(self, preset_id: str) -> DownloadOptions:
        settings = load_settings()
        presets = [*PresetDefaults.BUILT_IN, *settings.get("presets", [])]
        preset = next((p for p in presets if p.get("id") == preset_id), presets[0])
        return options_from_preset(preset, base_options(settings))

    @Slot(str, str, result=int)
    def addLinks(self, text: str, preset_id: str) -> int:
        """Queue every link in text (one per line) with a preset; returns how many are now in the list."""
        return self._add_links(text, preset_id, again=False)

    def download_again(self, url: str, preset_id: str) -> None:
        """Queue a link even if it was downloaded before (the Library's Download again)."""
        self._add_links(url, preset_id, again=True)

    def _add_links(self, text: str, preset_id: str, again: bool) -> int:
        links = [line.strip() for line in text.replace(",", "\n").split() if line.strip()]
        added, listed, problems = 0, 0, []
        try:
            options = self._preset_options(preset_id).with_changes(ignore_archive=again)
        except ValueError as error:
            self.notice.emit(f"The preset can't be used: {error}")
            return 0
        for link in links:
            try:
                source = source_from_url(link)
            except ValueError as error:
                problems.append(f"{link[:60]}: {error}")
                continue
            url = canonical_url(source, link)
            if self._listed(url, options):
                listed += 1
                continue
            self._add(url, source, options)
            added += 1
        if problems:
            self.notice.emit(f"{len(problems)} link(s) were skipped. " + problems[0])
        elif listed:
            self.notice.emit("Already in the list with the same choices." if listed == 1
                             else f"{listed} links are already in the list with the same choices.")
        if added:
            self._after_change()
        return added + listed

    def _listed(self, url: str, options: DownloadOptions) -> bool:
        """True when this link waits or downloads already with the same type and quality."""
        for job in self._context.store.jobs(ACTIVE_STATES):
            if job["url"] == url and not job["input_path"]:
                listed = DownloadOptions.from_dict(json.loads(job["options_json"]))
                if (listed.kind, listed.profile) == (options.kind, options.profile):
                    return True
        return False

    @Slot(str, "QVariantMap", "QVariantList", str, str, float, result=bool)
    def addJob(self, url: str, options: dict[str, Any], items: list[dict[str, Any]], title: str, thumbnail: str,
               not_before: float) -> bool:
        """Queue one analyzed link with its chosen options and items (from the Options panel)."""
        try:
            source = source_from_url(url)
            download_options = DownloadOptions.from_dict({**base_options(load_settings()).to_dict(), **options})
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

    def add_subscription_items(self, urls: list[str], source: Source, options: DownloadOptions,
                               subscription_id: int, account_id: int | None, not_before: float = 0.0) -> int:
        """Queue new uploads found by a subscription check (archived and filed under the subscription)."""
        for url in urls:
            self._add(url, source, options, subscription_id=subscription_id, account_id=account_id,
                      not_before=not_before, state="waiting_live" if not_before else "queued")
        if urls:
            self._after_change()
        return len(urls)

    def _add(self, url: str, source: Source, options: DownloadOptions, items: list[dict[str, Any]] | None = None,
             title: str = "", thumbnail: str = "", not_before: float = 0.0, subscription_id: int | None = None,
             account_id: int | None = None, state: str = "", input_path: str = "") -> int:
        root = str(self._context.download_root(options.kind))
        job_id = self._context.store.add_job(
            url, source.kind, source.source_id, source.site, options.to_dict(), root, source.tab, title, thumbnail,
            items, account_id, subscription_id, state or ("scheduled" if not_before > time.time() else "queued"),
            not_before, input_path)
        # A removed job's id can be given out again: nothing of the old job may carry over.
        self._clear_scratch(job_id)
        return job_id

    @Slot(int, "QVariantMap")
    def extractJobAudio(self, job_id: int, choices: dict[str, Any]) -> None:
        """Extract the audio of every video a download saved, with the Extract audio dialog's choices."""
        videos = [record for record in self._context.store.history_for_job(job_id) if record["kind"] == "video"]
        self._extract(videos, choices)

    @Slot(int, "QVariantMap")
    def extractAudio(self, history_id: int, choices: dict[str, Any]) -> None:
        """Extract the audio of one video in the library, with the Extract audio dialog's choices."""
        record = self._context.store.history_record(history_id)
        self._extract([record] if record is not None and record["kind"] == "video" else [], choices)

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
            self.notice.emit(f"These audio choices can't be used: {error}")
            return
        for record in fresh:
            path = record["filepath"]
            item_id = record["video_id"] or hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
            self._add(record["url"], Source("video", item_id, record["site"] or "generic"), options,
                      title=record["title"] or Path(path).stem, thumbnail=record["thumbnail"], input_path=path)
        self.notice.emit(f"Extracting the audio of {len(fresh)} video(s); it appears in Downloads and the Library.")
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
        self.resume(job_id)

    @Slot(int)
    def downloadAgain(self, job_id: int) -> None:
        """Download a finished download once more, even what the archive lists as downloaded before."""
        job = self._context.store.job(job_id)
        if job is None or job_id in self._running or job["input_path"]:
            return
        options = DownloadOptions.from_dict(json.loads(job["options_json"])).with_changes(ignore_archive=True)
        self._last_files.pop(job_id, None)
        self._context.store.update_job(job_id, options_json=json.dumps(options.to_dict()), skip_ids_json="[]")
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
    def remove(self, job_id: int, with_files: bool) -> None:
        """Take a download off the list; its files stay on disk unless `with_files` is set.

        With `with_files`, its saved files (and their captions, lyrics, and covers) go to the Recycle
        Bin and its unfinished files are deleted.
        """
        if job_id in self._running:
            self._running[job_id].stop("remove_files" if with_files else "remove")
            return
        job = self._context.store.job(job_id)
        if job is not None and with_files and not self._discard_files(job, set()):
            return
        self._forget_jobs([job_id])
        self._after_change()

    @Slot(int, int)
    def move(self, job_id: int, steps: int) -> None:
        """Move a download up or down the queue."""
        self._context.store.move_job(job_id, steps)
        self._after_change()

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

    @Slot(int, result="QVariantList")
    def items(self, job_id: int) -> list[dict[str, Any]]:
        """A playlist job's chosen items and how each went."""
        return [{"title": item["title"], "index": item["idx"], "state": item["state"], "message": item["message"]}
                for item in self._context.store.job_items(job_id)]

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
            QApplication.quit()
        elif action in ("sleep", "hibernate", "shutdown") and not power.perform(action):
            self.notice.emit(f"Windows didn't allow {action}.")

    @Slot()
    def cancelWhenDone(self) -> None:
        """Keep the PC on: the countdown was cancelled."""
        self._when_done = "nothing"
        self.changed.emit()

    @Slot(str)
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
        network = settings.get("network", {})
        downloads = settings.get("downloads", {})
        total = self._total_limit()
        self._applied_limit = total
        live = options.live_from_start or options.wait_for_video or job["state"] == "waiting_live"
        fragments = int(downloads.get("fragments", 0)) or DownloadDefaults.AUTO_FRAGMENTS
        rate = 0 if live else per_job_limit(total, len(self._running) + 1)
        options = options.with_changes(
            proxy=str(network.get("proxy", "")), force_ipv4=bool(network.get("force_ipv4", False)),
            limit_rate=rate, fragments=1 if rate else fragments)
        running = _Running(job["id"], archive, "" if job["input_path"] else job["site"], live)
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
        root = Path(job["output_root"])
        paths = RunPaths(root, Path(running.archive), context.job_dir(job["id"]), context.cache_dir)
        spec = JobSpec(job["url"], source, options, paths, auth, max_attempts, retry_delay, skip)

        def saved(info: dict[str, Any], path: Path) -> None:
            with running.lock:
                running.files.append((info, str(path)))

        executor = JobExecutor(spec, context.tools, on_file=saved, update_tools=self._tools.update_ytdlp,
                               runner=self._program_runner, lyrics_fetch=self._lyrics_fetch)
        running.executor = executor
        if running.stop_reason:
            return JobResult("stopped")
        try:
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
        roots = [self._context.download_root("video")]
        job = self._context.store.job(record["job_id"]) if record.get("job_id") else None
        if job is not None:
            roots.insert(0, Path(job["output_root"]))
        for root in roots:
            try:
                folder = video.parent.relative_to(root)
            except ValueError:
                continue
            return "" if folder == Path(".") else folder.as_posix()
        return ""  # a video saved elsewhere: its audio goes straight into the audio folder

    def _drain_files(self, running: _Running) -> None:
        """Record finished files in the library (on the GUI thread)."""
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
            history_id = self._context.store.add_history(
                path, job_id=running.job_id, video_id=str(info.get("id") or ""),
                site=job["site"] if job else "", kind="audio" if extension in AUDIO_EXTENSIONS else "video",
                title=str(info.get("title") or Path(path).stem),
                uploader=str(info.get("uploader") or info.get("channel") or ""),
                url=str(info.get("webpage_url") or ""),
                height=height if isinstance(height, int) else 0,
                duration=float(duration) if isinstance(duration, (int, float)) else 0.0,
                size=size, thumbnail=(job or {}).get("thumbnail", ""))
            if job is not None and info.get("id"):
                self._context.store.set_item_state(running.job_id, str(info["id"]), "done")
            self._last_files[running.job_id] = path
            self.fileSaved.emit(history_id, path)

    def _finished(self, running: _Running, result: JobResult) -> None:
        self._drain_files(running)
        self._running.pop(running.job_id, None)
        self._snapshots.pop(running.job_id, None)
        job = self._context.store.job(running.job_id)
        reason = running.stop_reason
        partials = running.executor.partial_files() if running.executor is not None else set()
        if job is None or reason == "remove":
            self._forget_jobs([running.job_id])
        elif reason == "remove_files":
            if self._discard_files(job, partials):
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
            elif reason in ("restart", "shutdown"):
                self._set_state(running.job_id, "queued", "", refresh=False)
            else:
                self._record_result(job, result)
        self.busyChanged.emit()
        self._after_change()
        self._check_finished_queue()

    def _record_result(self, job: dict[str, Any], result: JobResult) -> None:
        job_id = job["id"]
        failure = result.failure
        if result.state == "done" and not result.files and result.archived == 1 and not result.skipped:
            self._record_archived(job, result)
            return
        skip_ids = sorted({f.item_id for f in result.skipped if f.item_id} | set(json.loads(job["skip_ids_json"])))
        for skipped in result.skipped:
            self._context.store.set_item_state(job_id, skipped.item_id, "skipped", skipped.category.message)
        title = job["title"] or (result.files[0].stem if result.files else "")
        state = {"done": "done", "needs_auth": "needs_auth", "disk_full": "paused"}.get(result.state, "failed")
        message = result.message
        if result.rename_errors:
            message += f" ({len(result.rename_errors)} file name(s) couldn't be cleaned)"
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
            self.notice.emit("The disk is full, so the queue is paused. Free some space or choose another folder.")
            if notify:
                self._notifier.notify("Downloads paused", "The disk is full.")
        elif state == "failed" and notify:
            self._notifier.notify("Download failed", f"{name}\n{message}")

    def _keep_partials(self, job_id: int, partials: set[str]) -> None:
        """Remember a stopped download's unfinished files, with any kept from its earlier runs."""
        known = self._saved_partials(job_id)
        if not partials or partials <= known:
            return
        target = self._context.job_dir(job_id) / PARTIALS_FILE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(sorted(known | partials)), encoding="utf-8")
        except OSError as error:
            write_log(f"Unfinished files of download {job_id} couldn't be noted: {error}", "general")

    def _saved_partials(self, job_id: int) -> set[str]:
        try:
            saved = json.loads((self._context.job_dir(job_id) / PARTIALS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {item for item in saved if isinstance(item, str)} if isinstance(saved, list) else set()

    def _remove_partials(self, job: dict[str, Any], partials: set[str]) -> None:
        """Delete a download's unfinished files: those reported now and those noted when it stopped before."""
        saved = self._saved_partials(job["id"])
        archive = self._job_archive(job)
        if saved and any(r.archive == archive and r.job_id != job["id"] for r in self._running.values()):
            # Another download of the same videos is running and may be continuing these files.
            saved = set()
        else:
            (self._context.job_dir(job["id"]) / PARTIALS_FILE).unlink(missing_ok=True)
        remove_partials(partials | saved, Path(job["output_root"]) / ".incomplete")

    def _discard_files(self, job: dict[str, Any], partials: set[str]) -> bool:
        """Delete a download's unfinished files and move its saved ones to the Recycle Bin.

        False when Windows didn't move them (a file open in a player), so the download stays listed.
        """
        self._remove_partials(job, partials)
        records = self._context.store.history_for_job(job["id"])
        saved = [record["filepath"] for record in records if os.path.isfile(record["filepath"])]
        if not recycle_media(saved):
            self.notice.emit("Windows couldn't move the files to the Recycle Bin; they may be open in a player.")
            return False
        self._context.store.delete_history(record["id"] for record in records)
        if records:
            self.filesRemoved.emit()
        if saved:
            self.notice.emit(f"Moved {len(saved)} file(s) to the Recycle Bin.")
        return True

    def _forget_jobs(self, job_ids: list[int]) -> None:
        """Delete jobs with their scratch folders."""
        self._context.store.delete_jobs(job_ids)
        for job_id in job_ids:
            self._clear_scratch(job_id)

    def _clear_scratch(self, job_id: int) -> None:
        """Forget what this app kept about a job id: its scratch folder (journal, unfinished files) and Play file."""
        self._last_files.pop(job_id, None)
        shutil.rmtree(self._context.job_dir(job_id), ignore_errors=True)

    def _record_archived(self, job: dict[str, Any], result: JobResult) -> None:
        """One video the archive skipped and nothing else.

        While its file is still on disk, the job shows it as downloaded and Play opens that file. When
        the file is gone (deleted, or never in this library), asking for the video again means wanting
        it again, so the job downloads it once more past the archive.
        """
        existing = self._existing_file(job, result.archived_ids)
        options = DownloadOptions.from_dict(json.loads(job["options_json"]))
        if existing is None and not options.ignore_archive:
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
        """The library's newest file of this job's video, of the same type, that is still on disk."""
        kind = DownloadOptions.from_dict(json.loads(job["options_json"])).kind
        for record in self._context.store.history_of_video(job["site"], [*ids, job["source_id"]], job["url"]):
            if record["kind"] == kind and os.path.isfile(record["filepath"]):
                return record
        return None

    def _crashed(self, running: _Running, message: str) -> None:
        """The worker raised (a bug): record it instead of leaving the job running forever."""
        self._drain_files(running)
        self._running.pop(running.job_id, None)
        self._snapshots.pop(running.job_id, None)
        self._set_state(running.job_id, "failed", f"The download stopped unexpectedly: {message}", refresh=False)
        self.busyChanged.emit()
        self._after_change()

    def _set_state(self, job_id: int, state: str, message: str, refresh: bool = True) -> None:
        if self._context.store.job(job_id) is None:
            return
        self._context.store.update_job(job_id, state=state, message=message)
        if refresh:
            self._after_change()

    def _check_finished_queue(self) -> None:
        """Run the when-done action once nothing is left to do."""
        if self._running or not self._worked:
            return
        pending = self._context.store.jobs(_WAITING + ("retry_wait",))
        if pending and not self._paused:
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
        for job_id, running in list(self._running.items()):
            self._drain_files(running)
            if running.executor is None:
                continue
            snap = running.executor.snapshot()
            self._snapshots[job_id] = snap
            speeds += snap.speed
            fractions.append(snap.overall)
            self._model.update(job_id, _running_values(snap))
            job = self._context.store.job(job_id)
            if job is not None and not job["title"] and (snap.playlist_title or snap.title):
                source = source_of(job)
                title = snap.playlist_title if source.is_collection and snap.playlist_title else snap.title
                self._context.store.update_job(job_id, title=title, thumbnail=job["thumbnail"] or snap.thumbnail)
                self._model.update(job_id, {"title": title, "thumbnail": job["thumbnail"] or snap.thumbnail})
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
        self._pump()
        self._sync_model()
        self.changed.emit()

    def _sync_model(self) -> None:
        rows = []
        for job in self._context.store.jobs():
            snap = self._snapshots.get(job["id"]) if job["id"] in self._running else None
            if job["state"] == "done" and job["id"] not in self._last_files:
                last = self._context.store.last_file(job["id"])
                if not last and not job["files_done"]:
                    # "Already downloaded": its Play button plays the file the library has.
                    existing = self._existing_file(job, [])
                    last = existing["filepath"] if existing else ""
                self._last_files[job["id"]] = last
            rows.append(_job_row(job, snap, self._context.site(job["site"]).label, self._last_files.get(job["id"], "")))
        self._model.sync(rows)

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
            if running.executor is not None:
                self._keep_partials(running.job_id, running.executor.partial_files())
            self._context.store.update_job(running.job_id, state="queued")
        self._running.clear()
        self._clear_last_session()
        self._keep_awake(False)
        self._taskbar.close()


def _running_values(snap: Snapshot) -> dict[str, Any]:
    """The list values of a running job from its progress."""
    parts = []
    waiting = snap.wait_seconds >= 0 and snap.stage == "Waiting for the stream"
    progress = -1.0 if snap.is_live or waiting or snap.stage in ("Starting", "Starting download") else snap.overall
    if snap.stage in _POST_STAGES:
        if snap.stage == "Converting" and snap.convert_fraction >= 0:
            # The conversion's own share done; a list's bar keeps its overall progress.
            parts.append(f"{int(snap.convert_fraction * 100)}%")
            progress = snap.convert_fraction if snap.item_count <= 1 else snap.overall
        else:
            progress = -1.0
        if snap.downloaded:
            parts.append(f"{format_bytes(snap.downloaded)} downloaded")
    else:
        if snap.total:
            parts.append(f"{format_bytes(snap.downloaded)} of {format_bytes(snap.total)}")
        elif snap.downloaded:
            parts.append(format_bytes(snap.downloaded))
        if snap.speed:
            parts.append(f"{format_bytes(int(snap.speed))}/s")
    if snap.eta >= 0 and not snap.is_live:
        parts.append(f"{format_duration(snap.eta)} left")
    if snap.fragment and snap.stage not in _POST_STAGES:
        parts.append(f"part {snap.fragment}")
    item = f"Item {snap.item_index} of {snap.item_count}" if snap.item_count > 1 else ""
    stage = snap.stage + (f" ({format_duration(snap.wait_seconds)})" if waiting else "")
    return {"statusText": stage, "stage": stage, "progress": progress, "detail": "  ·  ".join(parts),
            "itemText": item}


# Stages after the download: ffmpeg works on the saved file, so there is no download speed.
_POST_STAGES = ("Merging", "Embedding", "Converting", "Cutting", "Finalizing", "Processing")

_STATE_TEXT = {
    "queued": "Waiting", "scheduled": "Scheduled", "waiting_live": "Waiting for the stream", "running": "Starting",
    "paused": "Paused", "retry_wait": "Retrying", "needs_auth": "Sign-in needed", "failed": "Failed",
    "done": "Done", "cancelled": "Cancelled",
}


def _job_row(job: dict[str, Any], snap: Snapshot | None, site_label: str, last_file: str = "") -> dict[str, Any]:
    """One row of the download list."""
    options = json.loads(job["options_json"])
    kind = "live" if options.get("live_from_start") or options.get("wait_for_video") else options.get("kind", "video")
    state = job["state"]
    detail = job["message"] or site_label
    if state in ("scheduled", "waiting_live") and job["not_before"]:
        detail = "Starts " + datetime.fromtimestamp(job["not_before"]).strftime("%a %H:%M")
    row = {
        "jobId": job["id"], "title": job["title"] or job["url"], "url": job["url"], "site": site_label, "kind": kind,
        "thumbnail": job["thumbnail"], "jobState": state, "statusText": _STATE_TEXT.get(state, state), "stage": "",
        "progress": 1.0 if state == "done" else 0.0, "detail": detail, "itemText": "", "message": job["message"],
        "action": job["action"], "folder": job["output_root"], "lastFile": last_file,
        "canPause": state in ("queued", "scheduled", "waiting_live", "running", "retry_wait"),
        "canResume": state in ("paused", "cancelled"),
        "canRetry": state in ("failed", "needs_auth", "done"),
        "canRedownload": state == "done" and not job["input_path"],
        "hasItems": job["items_total"] > 0,
    }
    if snap is not None:
        row.update(_running_values(snap))
    return row

