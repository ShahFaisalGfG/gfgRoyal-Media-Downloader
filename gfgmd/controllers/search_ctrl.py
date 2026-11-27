# search_ctrl.py - search from the link box: YouTube for videos, YouTube Music for songs, as results arrive

from __future__ import annotations

import re
import threading
import time
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from gfgmd.controllers.queue_ctrl import with_network
from gfgmd.core.analyze import AnalyzeError
from gfgmd.core.command import ARTIST_SUFFIX
from gfgmd.core.options import DownloadOptions
from gfgmd.core.quick_info import Fetch, quick_info
from gfgmd.core.runner import Runner, run_to_completion
from gfgmd.core.search import FIRST_RESULTS, MORE_RESULTS, SearchResult, clean_query, search
from gfgmd.core.sources import Source
from gfgmd.core.tools import ToolsMissing
from gfgmd.models.list_model import DictListModel
from gfgmd.services.context import AppContext
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.format import format_duration, format_views
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings

ROLES = ("resultId", "title", "url", "thumbnail", "detail", "checked", "live")
# A search shown again within this time comes from memory (as a link read does).
KEEP_SECONDS = 600
KEEP_SEARCHES = 20
_ARTIST_NOISE = re.compile(ARTIST_SUFFIX)
_NO_TOOLS = "The download tools aren't installed yet. Click Update tools."
_FAILED = "The search couldn't be run. Check your internet connection and try again."


class SearchController(QObject):
    """Runs a search on a worker and lists its results as they arrive; ticked results download together."""

    changed = Signal()
    # From the worker: (search number, one result).
    _found = Signal(int, object)

    def __init__(self, context: AppContext, quick_fetch: Fetch | None = None, runner: Runner = run_to_completion,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._quick_fetch = quick_fetch  # YouTube's oEmbed, for a song's artist; None leaves it out
        self._run_tool = runner  # how yt-dlp is run (a test runs a stand-in)
        self._runner = TaskRunner(1, self)
        self._details = TaskRunner(4, self)
        self._model = DictListModel(ROLES, "resultId", self)
        self._results: dict[str, SearchResult] = {}
        self._number = 0
        self._query = ""
        self._music = False
        self._limit = FIRST_RESULTS
        self._shown = False
        self._busy = False
        self._error = ""
        self._stop = threading.Event()
        # (words, music) -> (when, how many were asked for, the results in order)
        self._kept: dict[tuple[str, bool], tuple[float, int, list[SearchResult]]] = {}
        self._found.connect(self._add)
        self._model.countChanged.connect(self.changed)

    # ── Properties ────────────────────────────────────────────────────────

    @Property(QObject, constant=True)
    def model(self) -> DictListModel:
        """The results: title, thumbnail, a detail line (channel, length, views), and a check box."""
        return self._model

    @Property(bool, notify=changed)
    def shown(self) -> bool:
        """True while the search results take the place of Download options."""
        return self._shown

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=changed)
    def query(self) -> str:
        return self._query

    @Property(bool, notify=changed)
    def music(self) -> bool:
        """True for YouTube Music's songs, False for YouTube's videos."""
        return self._music

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._error

    @Property(bool, notify=changed)
    def canMore(self) -> bool:
        """True when "More results" can ask for more than the first page found."""
        return not self._busy and self._limit < MORE_RESULTS and len(self._results) >= self._limit

    @Property(int, notify=changed)
    def checkedCount(self) -> int:
        return sum(1 for row in self._model.rows() if row["checked"])

    # ── Actions ───────────────────────────────────────────────────────────

    @Slot(str, bool)
    def search(self, text: str, music: bool) -> None:
        """Search for these words: videos on YouTube, or (music) songs on YouTube Music."""
        words = clean_query(text)
        if not words:
            return
        self._shown = True
        if (words, music) == (self._query, self._music) and (self._busy or self._results):
            self.changed.emit()
            return  # the same search is showing or running
        self._query, self._music, self._limit = words, music, FIRST_RESULTS
        self._start(clear=True)

    @Slot()
    def more(self) -> None:
        """Ask for more results of the current search; the ones shown stay, with their check boxes."""
        if self.canMore:
            self._limit = MORE_RESULTS
            self._start(clear=False)

    @Slot()
    def close(self) -> None:
        """Hide the results and stop a search that is still running."""
        self._stop.set()
        self._number += 1
        self._shown, self._busy, self._error = False, False, ""
        self._query = ""
        self._results.clear()
        self._model.reset([])
        self.changed.emit()

    @Slot(str, bool)
    def setChecked(self, result_id: str, checked: bool) -> None:
        self._model.update(result_id, {"checked": checked})
        self.changed.emit()

    @Slot(bool)
    def checkAll(self, checked: bool) -> None:
        for row in self._model.rows():
            self._model.update(row["resultId"], {"checked": checked})
        self.changed.emit()

    @Slot(result=list)
    def checkedLinks(self) -> list[str]:
        """The links of the ticked results, in the order shown."""
        return [row["url"] for row in self._model.rows() if row["checked"]]

    def shutdown(self) -> None:
        self._stop.set()
        self._runner.shutdown(2000)
        self._details.shutdown(2000)

    # ── Running ───────────────────────────────────────────────────────────

    def _start(self, clear: bool) -> None:
        self._stop.set()
        self._stop = threading.Event()
        self._number += 1
        number, words, music, limit = self._number, self._query, self._music, self._limit
        if clear:
            self._results.clear()
            self._model.reset([])
        self._error = ""
        kept = self._kept.get((words, music))
        if kept is not None and time.monotonic() - kept[0] < KEEP_SECONDS and kept[1] >= limit:
            for result in kept[2]:
                self._add(number, result)
            self._busy = False
            self.changed.emit()
            return
        try:
            tools = self._context.tools()
        except ToolsMissing:
            self._error, self._busy = _NO_TOOLS, False
            self.changed.emit()
            return
        settings = load_settings()
        options = with_network(DownloadOptions(), settings)
        self._busy = True
        self.changed.emit()
        stop = self._stop
        self._runner.start(_search_or_failure, words, music, limit, tools, self._context.cache_dir, options, stop,
                           lambda result: self._found.emit(number, result), self._run_tool,
                           on_done=lambda outcome: self._finished(number, outcome),
                           on_error=lambda message: self._finished(number, ([], message)))

    def _add(self, number: int, result: SearchResult) -> None:
        if number != self._number or result.id in self._results:
            return
        self._results[result.id] = result
        self._model.append([self._row(result)])
        if self._music and not result.channel and self._quick_fetch is not None:
            self._details.start(quick_info, Source("video", result.id), f"https://www.youtube.com/watch?v={result.id}",
                                self._quick_fetch,
                                on_done=lambda info, n=number, rid=result.id: self._artist(n, rid, info.uploader if info else ""),
                                on_error=lambda _message: None)

    def _artist(self, number: int, result_id: str, uploader: str) -> None:
        """A song's artist arrived from YouTube's oEmbed ("Artist - Topic" read as "Artist")."""
        result = self._results.get(result_id)
        artist = _ARTIST_NOISE.sub("", uploader).strip()
        if number != self._number or result is None or not artist:
            return
        self._results[result_id] = result = replace(result, channel=artist)
        self._model.update(result_id, {"detail": _detail(result)})

    def _finished(self, number: int, outcome: tuple[list[SearchResult], str]) -> None:
        if number != self._number:
            return
        results, failure = outcome
        self._busy = False
        if failure:
            write_log(f"Search for \"{self._query}\" failed: {failure}", "general")
            if not self._results:
                self._error = _FAILED
        else:
            self._kept[(self._query, self._music)] = (time.monotonic(), self._limit, list(self._results.values()))
            while len(self._kept) > KEEP_SEARCHES:
                del self._kept[min(self._kept, key=lambda key: self._kept[key][0])]
            for result in results:  # any a slow queued signal hasn't shown yet
                self._add(number, result)
        self.changed.emit()

    @staticmethod
    def _row(result: SearchResult) -> dict[str, Any]:
        return {"resultId": result.id, "title": result.title, "url": result.url, "thumbnail": result.thumbnail,
                "detail": _detail(result), "checked": False, "live": result.live_status in ("is_live", "is_upcoming")}


def _detail(result: SearchResult) -> str:
    """The line under a result's title: "Channel  ·  4:37  ·  1.2M views"."""
    parts = [result.channel, format_duration(result.duration) if result.duration else "", format_views(result.views)]
    return "  ·  ".join(part for part in parts if part)


def _search_or_failure(words: str, music: bool, limit: int, tools: Any, cache_dir: Any, options: DownloadOptions,
                       stop: threading.Event, on_result: Any, runner: Runner) -> tuple[list[SearchResult], str]:
    """On the pool: run the search; a failure comes back as its reason (for the log), not as an exception."""
    try:
        return search(words, music, limit, tools, cache_dir, options, stop, on_result, runner), ""
    except AnalyzeError as error:
        return [], error.failure.category.message
