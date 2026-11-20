"""Run one download to the end: attempts, retries, file renaming, and the final verdict.

The executor is shared by the command-line tool and the app. Everything that touches the outside
world (the program runner, the clock, the wait between attempts) can be replaced, so tests drive
it with a fake yt-dlp and no network.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gfgmd.core.archive import ArchiveLock
from gfgmd.core.command import Auth, RunPaths, download_command
from gfgmd.core.errors import CATEGORIES, Failure, Policy, classify, judge
from gfgmd.core.lyrics import Fetch, add_lyrics
from gfgmd.core.naming import finalize_file
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import Event, ProgressTracker, Snapshot, read_convert_progress
from gfgmd.core.retry import retry_delay
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import Source
from gfgmd.core.tools import ToolSet

# Conversion and merge failures are retried this many times before the job gives up.
POSTPROCESS_ATTEMPTS = 2

Runner = Callable[..., tuple[int, bool]]


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

    @property
    def message(self) -> str:
        """A one-line summary for the user."""
        if self.failure is not None and self.state != "done":
            return self.failure.category.message
        if not self.files and self.archived and not self.skipped:
            return "Already downloaded" if self.archived == 1 else f"All {self.archived} already downloaded"
        parts = [f"{len(self.files)} file{'s' if len(self.files) != 1 else ''} saved"]
        if self.archived:
            parts.append(f"{self.archived} already downloaded")
        if self.skipped:
            parts.append(f"{len(self.skipped)} skipped")
        return ", ".join(parts)


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
    ) -> None:
        self._spec = spec
        self._tools = tools
        self._on_file = on_file
        self._on_event = on_event
        self._update_tools = update_tools
        self._runner = runner
        # How audio jobs look lyrics up online (lyrics.fetch_json); None uses the site's captions only.
        self._lyrics_fetch = lyrics_fetch
        self._stop = threading.Event()
        self._tracker = ProgressTracker()
        self._attempt = 0
        self._finalized: set[str] = set()
        self._partials: set[str] = set()

    def stop(self) -> None:
        """Stop the running attempt (or the wait before the next one)."""
        self._stop.set()

    @property
    def attempt(self) -> int:
        """The current attempt number, from 1."""
        return self._attempt

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

    def partial_files(self) -> set[str]:
        """Every partial file yt-dlp reported in any attempt (for removing a cancelled download)."""
        return self._partials | self._tracker.partials

    def run(self, sleep: Callable[[float], bool] | None = None) -> JobResult:
        """Run attempts until the job finishes, fails for good, or is stopped.

        `sleep(seconds)` waits between attempts and returns True when interrupted; the default
        waits on the stop event, so stop() cuts a five-minute wait short.
        """
        wait = sleep or self._stop.wait
        spec = self._spec
        result = JobResult("failed")
        skip_ids = list(spec.skip_ids)
        updated = False
        category_counts: dict[str, int] = {}
        spec.paths.prepare()
        lock = ArchiveLock(spec.paths.archive, timeout=1.0)
        while not lock.acquire():
            self._tracker.mark_stage("Waiting for another download of this list")
            if self._stop.is_set():
                result.state = "stopped"
                return result
        try:
            while True:
                self._attempt += 1
                result.attempts = self._attempt
                self._partials |= self._tracker.partials
                self._tracker = ProgressTracker()
                try:
                    tools = self._tools()
                except RuntimeError as error:
                    result.state, result.failure = "failed", Failure(CATEGORIES["tools"], str(error))
                    return result
                command = download_command(spec.url, spec.source, spec.options, tools, spec.paths, spec.auth,
                                           skip_ids)
                try:
                    code, stopped = self._runner(command, self._feed, self._stop)
                except OSError as error:
                    result.state, result.failure = "failed", Failure(CATEGORIES["tools"], f"yt-dlp didn't start: {error}")
                    return result
                self._finalize(tools, result)
                snap = self._tracker.snapshot()
                result.archived = max(result.archived, snap.archived)
                result.archived_ids += [i for i in self._tracker.archived_ids if i not in result.archived_ids]
                if stopped or self._stop.is_set():
                    result.state = "stopped"
                    return result
                if code == 0:
                    result.state = "done"
                    return result
                signed_in, single = spec.auth is not None, not spec.source.is_collection
                failures = [classify(event.text, str(event.data.get("id", "")), signed_in, single)
                            for event in self._tracker.errors]
                if not failures:
                    failures = [Failure(CATEGORIES["unknown"], f"yt-dlp exited with status {code}")]
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
                    # Done when anything else in the list was saved or was already saved before;
                    # a single video, or a list whose every item failed for good, has failed.
                    snap = self._tracker.snapshot()
                    others = bool(result.files) or snap.archived > 0 or snap.item_count > len(result.skipped)
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
                    self._tracker.mark_stage("Updating yt-dlp")
                    if self._update_tools():
                        continue
                if key == "postprocess" and category_counts[key] >= POSTPROCESS_ATTEMPTS:
                    result.state = "failed"
                    return result
                if spec.max_attempts and self._attempt >= spec.max_attempts:
                    result.state = "failed"
                    return result
                delay = retry_delay(self._attempt, spec.retry_delay, key)
                self._tracker.mark_stage(f"Retrying in {delay} s")
                if wait(delay):
                    result.state = "stopped"
                    return result
        finally:
            lock.release()

    def _feed(self, stream: str, line: str) -> None:
        event = self._tracker.feed(stream, line)
        if self._on_event is not None:
            self._on_event(event)

    def _finalize(self, tools: ToolSet, result: JobResult) -> None:
        """Rename every file yt-dlp reported (its printed lines and its own journal) to a clean name."""
        reported = list(self._tracker.files) + read_journal(self._spec.paths.journal)
        for info in reported:
            path = str(info.get("filepath") or "")
            if not path or path in self._finalized:
                continue
            self._finalized.add(path)
            try:
                final = finalize_file(Path(path), self._spec.paths.root, tools.ffprobe, self._spec.label_quality)
            except (OSError, RuntimeError, ValueError) as error:
                result.rename_errors.append(f"{Path(path).name}: {error}")
                final = Path(path)
            if final.exists():
                self._add_lyrics(final, info, tools)
                result.files.append(final)
                if self._on_file is not None:
                    self._on_file(info, final)

    def _add_lyrics(self, audio: Path, info: dict[str, Any], tools: ToolSet) -> None:
        """Save timed lyrics beside a finished audio file and put plain lyrics in its tags."""
        options = self._spec.options
        if options.kind != "audio" or not options.lyrics:
            return
        self._tracker.mark_stage("Adding lyrics")
        online = options.lyrics_online and self._lyrics_fetch is not None
        add_lyrics(audio, info, options.subtitle_langs, online, tools.ffmpeg, tools.ffprobe,
                   self._lyrics_fetch or (lambda _url: None))


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
