"""Run one download to the end: attempts, retries, file renaming, and the final verdict.

The executor is shared by the command-line tool and the app. Everything that touches the outside
world (the program runner, the clock, the wait between attempts) can be replaced, so tests drive
it with a fake yt-dlp and no network.

Each saved file is finished (renamed, given its lyrics, reported) as soon as yt-dlp moves it into
place, so a playlist's songs reach the library while the rest download. A video whose download stops
moving is set aside: the rest of the list goes first, and it gets fresh links afterwards. A signed-in
list's video that fails in a way the sign-in can cause is downloaded once more by its own link, without
the sign-in, into the list's folder.
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from gfgmd.core.archive import ArchiveLock
from gfgmd.core.command import Auth, RunPaths, download_command, run_marker, url_args
from gfgmd.core.errors import CATEGORIES, Failure, Policy, classify, folder_failure, given_up, judge
from gfgmd.core.lyrics import Fetch, add_lyrics
from gfgmd.core.naming import finalize_file, inside_root
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import PHASE_WAIT, Event, ProgressTracker, Snapshot, listed_entries, read_convert_progress
from gfgmd.core.retry import retry_delay
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import Source
from gfgmd.core.tools import ToolSet
from gfgmd.utils.format import count_media, format_wait, media_noun

# Conversion and merge failures are retried this many times before the job gives up.
POSTPROCESS_ATTEMPTS = 2
# A playlist's video that fails for a temporary reason this many attempts running is skipped, so one
# video can't keep the whole list trying again forever.
ITEM_ATTEMPTS = 3
# A video downloading without a byte or a new part for this long has stalled (its server stopped
# answering); yt-dlp's own retries would hold the whole list for an hour.
STALL_SECONDS = 90.0
# How often the stall check looks.
_WATCH_EVERY = 1.0
# After this many stalled videos in one run, each further one waits before the list goes on: every
# restart reads the whole playlist again, and a site may count those requests.
MAX_SET_ASIDE = 5
# Marks a playlist file in the finishing queue, which otherwise holds saved files' details.
_LIST_KEY = "__playlist_file__"
# The format names in "Converting to MP3".
_FORMAT_LABELS = {"mp3": "MP3", "m4a": "M4A", "opus": "Opus", "vorbis": "OGG", "flac": "FLAC", "wav": "WAV"}

Runner = Callable[..., tuple[int, bool]]
# ("listed", [entry dicts]) or ("state", (video id, state, message)); see JobExecutor.take_updates.
Update = tuple[str, Any]


@dataclass(frozen=True)
class JobSpec:
    """Everything one download needs."""

    url: str
    source: Source
    options: DownloadOptions
    paths: RunPaths
    auth: Auth | None = None
    max_attempts: int = 0  # 0 keeps retrying temporary failures until stopped
    retry_delay: int = 10
    skip_ids: tuple[str, ...] = ()
    # Links downloaded in place of `url` (a subscription's new uploads), and a folder named outright.
    urls: tuple[str, ...] = ()
    folder: str = ""

    @property
    def label_quality(self) -> bool:
        """True when finished video names end in their measured quality."""
        return self.options.filename_style != "title"


@dataclass
class JobResult:
    """How a download ended."""

    # done, failed, stopped, needs_auth, disk_full
    state: str
    attempts: int = 0
    files: list[Path] = field(default_factory=list)
    skipped: list[Failure] = field(default_factory=list)
    failure: Failure | None = None
    rename_errors: list[str] = field(default_factory=list)
    # Videos the archive skipped as downloaded before, and their IDs when yt-dlp named them.
    archived: int = 0
    archived_ids: list[str] = field(default_factory=list)
    # "audio" or "video", for "3 songs saved".
    kind: str = "video"

    @property
    def message(self) -> str:
        """A one-line summary for the user."""
        if self.failure is not None and self.state != "done":
            return self.failure.category.final
        if not self.files and self.archived and not self.skipped:
            return "Already downloaded" if self.archived == 1 else f"All {self.archived} were downloaded before"
        if not self.files and not self.archived and not self.skipped and self.state == "done":
            return "There was nothing to download: the list is empty"
        # "7 downloaded before, 1 couldn't be downloaded": a count of nothing saved is left out.
        parts = [f"{count_media(len(self.files), self.kind)} saved"] if self.files else []
        if self.archived:
            parts.append(f"{self.archived} downloaded before")
        if self.skipped:
            failed = len(self.skipped)
            parts.append(f"{failed if parts else count_media(failed, self.kind)} couldn't be downloaded")
        return ", ".join(parts) or f"{count_media(0, self.kind)} saved"


class JobExecutor:
    """Download one link with retries; call run() on a worker thread and stop() from any thread."""

    def __init__(
        self,
        spec: JobSpec,
        tools: Callable[[], ToolSet],
        on_file: Callable[[dict[str, Any], Path], None] | None = None,
        on_event: Callable[[Event], None] | None = None,
        update_tools: Callable[[], bool] | None = None,
        runner: Runner = run_to_completion,
        lyrics_fetch: Fetch | None = None,
        stall_seconds: float = STALL_SECONDS,
    ) -> None:
        self._spec = spec
        self._tools = tools
        self._on_file = on_file
        self._on_event = on_event
        self._update_tools = update_tools
        self._runner = runner
        # How audio jobs look lyrics up online (lyrics.fetch_json); None uses the site's captions only.
        self._lyrics_fetch = lyrics_fetch
        self._stall_seconds = stall_seconds
        self._stop = threading.Event()
        self._attempt_stop = threading.Event()
        # This run's marker for the lines the app reads (see command.run_marker).
        self._marker = run_marker()
        self._tracker = self._new_tracker()
        self._partials: set[str] = set()
        # Finished files, handled one at a time on their own thread while yt-dlp goes on.
        self._finish_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._files_lock = threading.Lock()
        self._finalized: set[str] = set()
        self._saved: list[Path] = []
        self._rename_errors: list[str] = []
        self._attempt_tools: ToolSet | None = None
        # Attempts that waited or failed (set-aside videos restart at once and don't count).
        self._retries = 0
        # IDs of the videos this run saved, which a later attempt's archive check names as downloaded.
        self._saved_ids: set[str] = set()
        self._updates_lock = threading.Lock()
        self._updates: list[Update] = []
        # How many videos the current attempt's playlist files listed so far, and how many list files it
        # has read (its first names the download).
        self._list_offset = 0
        self._attempt_lists = 0
        # The IDs of the lists read (a playlist, a channel's tabs), which are no video of their own,
        # and the parts of the link that can name the list.
        self._list_ids: set[str] = set()
        self._link_names = _link_names(spec.url)
        # Each video's own link and its folder below the download root ("" for the root itself), from
        # the item line yt-dlp prints before downloading it.
        self._places: dict[str, tuple[str, str]] = {}

    def stop(self) -> None:
        """Stop the running attempt (or the wait before the next one)."""
        self._stop.set()
        self._attempt_stop.set()

    @property
    def retries(self) -> int:
        """How many attempts ended in a failure the download waits out (what "Attempt 2 didn't finish" counts)."""
        return self._retries

    def snapshot(self) -> Snapshot:
        """The current attempt's progress, with an audio conversion's from ffmpeg's progress file."""
        tracker = self._tracker
        snap = tracker.snapshot()
        if tracker.converting_since and snap.duration > 0:
            done = read_convert_progress(self._spec.paths.convert_progress, tracker.converting_since)
            if done is not None:
                seconds, speed = done
                snap.convert_fraction = min(seconds / snap.duration, 1.0)
                snap.eta = int((snap.duration - seconds) / speed) if speed > 0 and seconds < snap.duration else -1
        return snap

    def take_updates(self) -> list[Update]:
        """What happened to a playlist's videos since the last call, from any thread.

        ("listed", entries) when yt-dlp listed the playlist, and ("list_title", its name) for the first
        list of an attempt; ("dropped", id) for an entry that turned out to be a list of its own (its
        videos are listed instead); ("state", (id, state, message)) with
        state "archived" (downloaded before), "skipped" (can't be downloaded, such as a private video),
        "failed" (failed this time), "deferred" (its server stopped answering; tried again after the
        rest), or "pending" (being tried again).
        """
        self._pull_tracker()
        with self._updates_lock:
            updates, self._updates = self._updates, []
        return updates

    def _pull_tracker(self) -> None:
        """Move the tracker's "downloaded before" marks here."""
        self._push(self._tracker.take_updates())

    def partial_files(self) -> set[str]:
        """Every partial file yt-dlp reported in any attempt (for removing a cancelled download)."""
        return self._partials | self._tracker.partials

    def run(self, sleep: Callable[[float], bool] | None = None) -> JobResult:
        """Run attempts until the job finishes, fails for good, or is stopped.

        `sleep(seconds)` waits between attempts and returns True when interrupted; the default
        waits on the stop event, so stop() cuts a five-minute wait short.
        """
        spec = self._spec
        result = JobResult("failed", kind=spec.options.kind)
        lock = ArchiveLock(spec.paths.archive, timeout=1.0)
        try:
            spec.paths.prepare()
            while not lock.acquire():
                self._tracker.mark_stage("Waiting for another download of the same videos to finish", PHASE_WAIT)
                if self._stop.is_set():
                    result.state = "stopped"
                    return result
        except OSError as error:  # the download folder is full, not allowed, or not there
            result.failure = folder_failure(error)
            result.state = "disk_full" if result.failure.category.key == "disk_full" else "failed"
            return result
        finisher = threading.Thread(target=self._finish_files, daemon=True, name="gfgmd-finish")
        finisher.start()
        try:
            return self._attempts(result, sleep or self._stop.wait)
        finally:
            self._finish_queue.put(None)
            finisher.join()
            lock.release()

    def _attempts(self, result: JobResult, wait: Callable[[float], bool]) -> JobResult:
        """The attempt loop (see run())."""
        spec = self._spec
        skip_ids = list(spec.skip_ids)
        updated = False
        category_counts: dict[str, int] = {}
        # Videos whose download stalled, left out until the rest is done; those being tried again; and
        # how many times one was set aside in this run.
        deferred: list[str] = []
        released: set[str] = set()
        set_aside = 0
        # How many attempts running each playlist video failed for a reason of its own, and how many
        # times each one stalled.
        item_failures: dict[str, int] = {}
        stall_counts: dict[str, int] = {}
        # A signed-in list's videos already downloaded once on their own without the sign-in.
        alone: set[str] = set()
        while True:
            # Tries so far, this one included; a restart after setting a stalled video aside isn't one.
            result.attempts = self._retries + 1
            self._begin_attempt()
            try:
                tools = self._tools()
            except RuntimeError as error:
                result.state, result.failure = "failed", Failure(CATEGORIES["tools"], str(error))
                return result
            self._attempt_tools = tools
            with self._files_lock:
                saved_before = len(self._saved)
            # Set-aside videos go first, so the filter's length limit never drops them.
            command = download_command(spec.url, spec.source, spec.options, tools, spec.paths, spec.auth,
                                       deferred + skip_ids, urls=spec.urls, folder=spec.folder, marker=self._marker)
            stalled: list[str] = []
            try:
                code, stopped = self._run_attempt(command, stalled)
            except OSError as error:
                result.state, result.failure = "failed", Failure(CATEGORIES["tools"], f"yt-dlp didn't start: {error}")
                return result
            self._finalize(result)
            self._count_archived(result, saved_before)
            if self._stop.is_set():
                result.state = "stopped"
                return result
            signed_in, single = spec.auth is not None, not spec.source.is_collection
            failures = [classify(event.text, self._video_id(str(event.data.get("id", ""))), signed_in, single)
                        for event in self._tracker.errors if not _harmless(event.text)]
            # Whether this attempt got anywhere (saved a video, or found one saved before): only then
            # does a video's own failure count against it, not when the whole connection is down.
            with self._files_lock:
                progressed = len(self._saved) > saved_before
            progressed = progressed or self._tracker.snapshot().archived > 0
            if stalled and code != 0:
                # Whatever can never download is left out from now on, as after any attempt.
                for failure in failures:
                    if failure.category.policy is Policy.SKIP and failure.item_id and failure.item_id not in skip_ids:
                        skip_ids.append(failure.item_id)
                        result.skipped.append(failure)
                stuck = stalled[0]
                result.failure = Failure(CATEGORIES["stalled"], f"No progress for {self._stall_seconds:.0f} s",
                                         stuck)
                if not spec.source.is_collection:
                    # One video: nothing else to go on with, so wait as for a dropped connection.
                    if self._out_of_retries(result) or self._wait_to_retry(wait, "stalled", result):
                        return result
                    continue
                set_aside += 1
                stall_counts[stuck] = stall_counts.get(stuck, 0) + 1
                if stall_counts[stuck] >= ITEM_ATTEMPTS:
                    # Its server never answers: left out, so the rest of the list can finish.
                    released.discard(stuck)
                    if stuck in deferred:
                        deferred.remove(stuck)
                    if stuck not in skip_ids:
                        skip_ids.append(stuck)
                        result.skipped.append(given_up(result.failure))
                    self._push([("state", (stuck, "skipped", CATEGORIES["stalled"].final))])
                    continue
                # It stalled again after its second chance, or while it should have been left out
                # (the filter can't name every ID), or the list keeps stalling: wait before going on.
                again = stuck in released or stuck in deferred or set_aside > MAX_SET_ASIDE
                released.discard(stuck)
                if stuck not in deferred:
                    deferred.append(stuck)
                self._push([("state", (stuck, "deferred", CATEGORIES["stalled"].message))])
                if again and (self._out_of_retries(result) or self._wait_to_retry(wait, "stalled", result)):
                    return result
                continue  # the rest of the list goes first
            if stopped and code != 0:
                result.state = "stopped"
                return result
            if code != 0 and not failures and any(_harmless(event.text) for event in self._tracker.errors):
                code = 0  # only yt-dlp's own note that it couldn't rewrite the playlist file
            if code != 0 and failures and spec.auth is not None and spec.source.is_collection:
                failures = self._without_sign_in(failures, alone, result)
                if self._stop.is_set():
                    result.state = "stopped"
                    return result
                if not failures:
                    code = 0  # the videos that failed were saved on their own
            if code == 0:
                if deferred:
                    self._release(deferred, released)
                    continue
                result.state = "done"
                return result
            if not failures:
                failures = [Failure(CATEGORIES["unknown"], f"yt-dlp exited with status {code}")]
            if spec.source.is_collection:
                failures = _give_up_on_repeats(failures, item_failures, progressed)
            verdict = judge(failures)
            result.failure = verdict.headline
            for failure in verdict.failures:
                if failure.category.policy is Policy.SKIP and failure.item_id and failure.item_id not in skip_ids:
                    skip_ids.append(failure.item_id)
                    result.skipped.append(failure)
            policy = verdict.policy
            headline = verdict.headline
            key = headline.category.key if headline else "unknown"
            category_counts[key] = category_counts.get(key, 0) + 1
            if policy is Policy.SKIP:
                if deferred:
                    # The rest is done apart from what can't be downloaded; now the stalled videos.
                    self._release(deferred, released)
                    continue
                # Done when anything else in the list was saved or was already saved before;
                # a single video, or a list whose every item failed for good, has failed.
                snap = self._tracker.snapshot()
                others = bool(result.files) or result.archived > 0 or snap.item_count > len(result.skipped)
                result.state = "done" if others else "failed"
                return result
            if policy is Policy.STOP:
                result.state = "needs_auth" if headline and headline.category.action == "signin" else "failed"
                return result
            if policy is Policy.PAUSE_QUEUE:
                result.state = "disk_full"
                return result
            if policy is Policy.UPDATE and not updated and self._update_tools is not None:
                updated = True
                self._tracker.mark_stage("Updating the download tools", PHASE_WAIT)
                if self._update_tools():
                    continue
            one_video = spec.source.is_collection and headline is not None and bool(headline.item_id)
            if key == "postprocess" and category_counts[key] >= POSTPROCESS_ATTEMPTS and not one_video:
                result.state = "failed"
                return result
            if self._out_of_retries(result) or self._wait_to_retry(wait, key, result):
                return result

    def _count_archived(self, result: JobResult, saved_before: int) -> None:
        """Note the videos the archive skipped, leaving out this run's own: a later attempt walks the list
        again and finds the `saved_before` files earlier attempts saved there (yt-dlp often names them
        by title, so they can't all be told apart by ID)."""
        tracker = self._tracker
        with self._files_lock:
            own = sum(1 for video_id in tracker.archived_ids if video_id in self._saved_ids)
            saved = set(self._saved_ids)
        result.archived = max(result.archived, tracker.snapshot().archived - max(own, saved_before))
        result.archived_ids += [video_id for video_id in tracker.archived_ids
                                if video_id not in result.archived_ids and video_id not in saved]

    def _out_of_retries(self, result: JobResult) -> bool:
        """Count a retry; True (with the job failed) when the attempts allowed are used up."""
        self._retries += 1
        if self._spec.max_attempts and self._retries >= self._spec.max_attempts:
            result.state = "failed"
            return True
        return False

    def _wait_to_retry(self, wait: Callable[[float], bool], key: str, result: JobResult) -> bool:
        """Wait before the next attempt; True (with the job stopped) when stopped meanwhile."""
        delay = retry_delay(self._retries, self._spec.retry_delay, key)
        reason = result.failure.category.cause if result.failure is not None else ""
        self._tracker.mark_stage(f"Trying again {format_wait(delay)}", PHASE_WAIT, reason)
        if wait(delay) or self._stop.is_set():
            result.state = "stopped"
            return True
        return False

    def _without_sign_in(self, failures: list[Failure], tried: set[str], result: JobResult) -> list[Failure]:
        """Download a signed-in list's videos that failed in a way the sign-in can cause once more, each by
        its own link without the sign-in, into the folder yt-dlp chose for it; the failures of those saved
        are left out. A video that fails this way too keeps its first failure, and its row says so."""
        with self._updates_lock:
            places = dict(self._places)
        retried: dict[str, Failure] = {}  # each video's first failure
        for failure in failures:
            item = failure.item_id
            fresh = item not in tried and item not in retried
            if fresh and item in places and failure.category.key in _SIGN_IN_MAY_CAUSE:
                retried[item] = failure
        if not retried:
            return failures
        tried.update(retried)
        folders: dict[str, list[str]] = {}
        for item in retried:
            link, folder = places[item]
            folders.setdefault(folder, []).append(link)
        list_tracker = self._tracker
        self._tracker = self._new_tracker()
        self._tracker.mark_stage("Trying without your sign-in")
        self._push([("state", (item, "pending", "")) for item in retried])
        try:
            for folder, links in folders.items():
                if not self._stop.is_set():
                    self._run_alone(links, folder)
        finally:
            self._pull_tracker()
            self._partials |= self._tracker.partials
            self._tracker = list_tracker
        self._finalize(result)
        with self._files_lock:
            saved = set(self._saved_ids)
        self._push([("state", (item, "skipped" if failure.category.policy is Policy.SKIP else "failed",
                               failure.category.final)) for item, failure in retried.items() if item not in saved])
        return [failure for failure in failures if failure.item_id not in saved]

    def _run_alone(self, links: list[str], folder: str) -> None:
        """One yt-dlp run for videos by their own links, without the sign-in, saved in `folder`."""
        spec, tools = self._spec, self._attempt_tools
        if tools is None:
            return
        # Whatever the list's choices picked out of it (--playlist-items) doesn't apply to its videos' own links.
        options = spec.options.with_changes(items="")
        command = download_command(links[0], Source("video", "", spec.source.site), options, tools, spec.paths,
                                   urls=links, folder=folder, marker=self._marker)
        batch = url_args(links, spec.paths.job_dir)[1]
        try:
            if batch:
                (spec.paths.job_dir / "urls.txt").write_text(batch, encoding="utf-8")
            self._run_attempt(command, [])
        except OSError:
            return  # yt-dlp didn't start: the videos keep their failures

    def _release(self, deferred: list[str], released: set[str]) -> None:
        """Try the set-aside videos again, with fresh links, now that the rest of the list is done."""
        self._push([("state", (item, "pending", "")) for item in deferred])
        released.update(deferred)
        deferred.clear()

    def _begin_attempt(self) -> None:
        """A fresh tracker, keeping what the last one noted; and a fresh playlist file to read."""
        self._pull_tracker()
        self._partials |= self._tracker.partials
        self._tracker = self._new_tracker()
        with self._updates_lock:
            self._list_offset = 0
            self._attempt_lists = 0
        # yt-dlp leaves an existing playlist file alone, and then never says where it is.
        shutil.rmtree(self._spec.paths.lists, ignore_errors=True)
        batch = url_args(self._spec.urls, self._spec.paths.job_dir)[1] if self._spec.urls else ""
        if batch:
            self._spec.paths.job_dir.mkdir(parents=True, exist_ok=True)
            (self._spec.paths.job_dir / "urls.txt").write_text(batch, encoding="utf-8")

    def _new_tracker(self) -> ProgressTracker:
        options = self._spec.options
        label = _FORMAT_LABELS.get(options.audio_format, "") if options.kind == "audio" else ""
        return ProgressTracker(convert_label=label, marker=self._marker)

    def _run_attempt(self, command: list[str], stalled: list[str]) -> tuple[int, bool]:
        """Run yt-dlp once, stopping it when the job stops or its current video stalls (noted in `stalled`)."""
        attempt_stop = threading.Event()
        self._attempt_stop = attempt_stop
        if self._stop.is_set():
            attempt_stop.set()
        done = threading.Event()

        def watch() -> None:
            while not done.wait(_WATCH_EVERY):
                if self._stop.is_set():
                    attempt_stop.set()
                    return
                stuck = self._tracker.stalled(self._stall_seconds)
                if stuck:
                    stalled.append(stuck)
                    attempt_stop.set()
                    return

        watcher = threading.Thread(target=watch, daemon=True, name="gfgmd-stall-check")
        watcher.start()
        try:
            return self._runner(command, self._feed, attempt_stop)
        finally:
            done.set()
            watcher.join()

    def _push(self, updates: list[Update]) -> None:
        if updates:
            with self._updates_lock:
                self._updates.extend(updates)

    def _feed(self, stream: str, line: str) -> None:
        tracker = self._tracker
        event = tracker.feed(stream, line)
        listed = tracker.pop_list_file()
        if listed:
            # Read on the finishing thread: a channel's list can be megabytes, and the reader must keep up.
            self._finish_queue.put({_LIST_KEY: listed})
        self._pull_tracker()
        if event.kind == "item":
            self._note_place(event.data)
            self._note_scratch(tracker, event.data)
        elif event.kind == "file":
            self._finish_queue.put(dict(event.data))
        elif event.kind == "error" and event.data.get("id") and not self._is_list(str(event.data["id"])):
            spec = self._spec
            failure = classify(event.text, str(event.data["id"]), spec.auth is not None, not spec.source.is_collection)
            state = "skipped" if failure.category.policy is Policy.SKIP else "failed"
            self._push([("state", (failure.item_id, state, failure.category.final))])
        if self._on_event is not None:
            self._on_event(event)

    def _note_place(self, data: dict[str, Any]) -> None:
        """Note a video's own link and the folder yt-dlp is about to save it in."""
        video_id, link, filename = (str(data.get(key) or "") for key in ("id", "webpage_url", "filename"))
        if not video_id or not filename or not link.startswith(("https://", "http://")):
            return
        try:
            folder = Path(filename).parent.relative_to(self._spec.paths.root)
        except ValueError:
            return  # never outside the download folder
        with self._updates_lock:
            self._places[video_id] = (link, "" if folder == Path(".") else folder.as_posix())

    def _note_scratch(self, tracker: ProgressTracker, data: dict[str, Any]) -> None:
        """Note where yt-dlp keeps a video's unfinished files before any progress line names them.

        It writes the thumbnail, an empty part, and the fragment list there first, so a video whose
        server never sends a byte (it stalls, or is cancelled first) still has them deleted with the
        download's other unfinished files.
        """
        filename = str(data.get("filename") or "")
        if not filename:
            return
        try:
            relative = Path(filename).relative_to(self._spec.paths.root)
        except ValueError:
            return  # never outside the download folder
        tracker.partials.add(str(self._spec.paths.incomplete / relative))

    def _video_id(self, item_id: str) -> str:
        """The ID an error names when it is a video's; "" for the list's own (an error about the list)."""
        return "" if item_id and self._is_list(item_id) else item_id

    def _is_list(self, item_id: str) -> bool:
        """True for the playlist's or a tab's own ID (a part of its link, or a list file read): an error
        about the list, not one of its videos, so it gets no row of its own."""
        with self._updates_lock:
            return item_id in self._link_names or item_id in self._list_ids

    def _finish_files(self) -> None:
        """On its own thread: finish each saved file as yt-dlp reports it, until run() ends.

        Nothing may end this thread early: each attempt waits for it to finish every file.
        """
        while True:
            info = self._finish_queue.get()
            try:
                if info is None:
                    return
                if _LIST_KEY in info:
                    self._read_list(str(info[_LIST_KEY]))
                else:
                    self._finish(info)
            except Exception as error:  # the thread's boundary: note it with the file, go on with the next
                name = Path(str(info.get("filepath") or info.get(_LIST_KEY) or "")).name if info else ""
                with self._files_lock:
                    self._rename_errors.append(f"{name}: {error!r}")
            finally:
                self._finish_queue.task_done()

    def _read_list(self, path: str) -> None:
        """Hand on the videos a playlist file lists; a list inside another (a tab, an album) replaces its entry.

        Only files in this run's own list folder are read, whatever yt-dlp's output names.
        """
        if not inside_root(Path(path), self._spec.paths.lists):
            return
        try:
            info = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # without the list, the videos still show as they download
        if not isinstance(info, dict):
            return
        with self._updates_lock:
            first = self._attempt_lists == 0
            self._attempt_lists += 1
            entries = listed_entries(info, self._list_offset)
            self._list_offset += len(entries)
        updates: list[Update] = []
        if first and info.get("title"):
            updates.append(("list_title", str(info["title"])))
        if info.get("id"):
            updates.append(("dropped", str(info["id"])))
            with self._updates_lock:
                self._list_ids.add(str(info["id"]))
        if entries:
            updates.append(("listed", entries))
        self._push(updates)

    def _finish(self, info: dict[str, Any]) -> None:
        """Rename one saved file to its clean name, add lyrics to a song, and report it (once per file)."""
        path = str(info.get("filepath") or "")
        tools = self._attempt_tools
        with self._files_lock:
            if not path or path in self._finalized or tools is None:
                return
            self._finalized.add(path)
        if not inside_root(Path(path), self._spec.paths.root):
            return  # yt-dlp saves only in the download folder; anything else is never touched
        try:
            final = finalize_file(Path(path), self._spec.paths.root, tools.ffprobe, self._spec.label_quality)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            with self._files_lock:
                self._rename_errors.append(f"{Path(path).name}: {error}")
            final = Path(path)
        if not final.exists():
            return
        self._add_lyrics(final, info, tools)
        with self._files_lock:
            self._saved.append(final)
            if info.get("id"):
                self._saved_ids.add(str(info["id"]))
        if self._on_file is not None:
            self._on_file(info, final)

    def _finalize(self, result: JobResult) -> None:
        """After an attempt: finish what yt-dlp reported, then anything only its own journal recorded."""
        self._finish_queue.join()
        for info in read_journal(self._spec.paths.journal):
            self._finish_queue.put(info)
        self._finish_queue.join()
        with self._files_lock:
            result.files = list(self._saved)
            result.rename_errors = list(self._rename_errors)

    def _add_lyrics(self, audio: Path, info: dict[str, Any], tools: ToolSet) -> None:
        """Save timed lyrics beside a finished audio file and put plain lyrics in its tags."""
        options = self._spec.options
        if options.kind != "audio" or not options.lyrics:
            return
        online = options.lyrics_online and self._lyrics_fetch is not None
        add_lyrics(audio, info, options.subtitle_langs, online, tools.ffmpeg, tools.ffprobe,
                   self._lyrics_fetch or (lambda _url: None))


def _link_names(url: str) -> set[str]:
    """The parts of a list's link that can name the list itself (path parts, query values), but not a
    video it also names (a watch link's v=, which yt-dlp downloads alone when the list can't be read)."""
    parts = urlsplit(url)
    names = {part for part in parts.path.split("/") if part}
    return names | {value for key, value in parse_qsl(parts.query) if key != "v" and value}


def _give_up_on_repeats(failures: list[Failure], counts: dict[str, int], progressed: bool) -> list[Failure]:
    """Count each playlist video's temporary failures of its own; one that failed ITEM_ATTEMPTS attempts
    running is skipped from now on, so the rest of the list can finish. A video that went through is
    forgotten. Rate limits and bot checks never count, nor does an attempt that got nowhere (the whole
    list failing at once means the connection, not the videos)."""
    failing = {failure.item_id for failure in failures
               if failure.item_id and failure.category.policy in (Policy.RETRY, Policy.UPDATE)
               and failure.category.key not in _NOT_THE_VIDEO}
    for item in list(counts):
        if item not in failing:
            del counts[item]
    if not progressed:
        return failures
    for item in failing:
        counts[item] = counts.get(item, 0) + 1
    return [given_up(failure) if failure.item_id in failing and counts[failure.item_id] >= ITEM_ATTEMPTS
            else failure for failure in failures]


# A signed-in list's video failures that a download without the sign-in can get past: a site can refuse
# a signed-in download of a video anyone can watch (YouTube's signed-in players can break off partway or
# offer fewer formats).
_SIGN_IN_MAY_CAUSE = frozenset({"network", "unknown", "bot_check", "extractor_broken", "format", "no_formats"})

# Temporary failures that say nothing about one video: the site limiting downloads, a bot check, or a
# stall (counted on its own). A dropped connection counts only when the same attempt got somewhere,
# so an outage never does, while a video whose server never answers your PC is given up on.
_NOT_THE_VIDEO = frozenset({"rate_limited", "bot_check", "stalled"})


def _harmless(error: str) -> bool:
    """True for yt-dlp's note that it couldn't rewrite a playlist file at the end; the videos are fine."""
    return error.startswith("Cannot write") and "playlist metadata" in error


def read_journal(journal: Path) -> list[dict[str, Any]]:
    """The finished files yt-dlp wrote to its journal, skipping a line cut short by a crash."""
    try:
        text = journal.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries
