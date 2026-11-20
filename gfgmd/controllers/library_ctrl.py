# library_ctrl.py - finished downloads: search, filters, paging, playlist groups, and actions on files
#
# A playlist's or channel's files show as one group row (they share a folder under the download
# root), opening into its files in playlist order; files saved on their own are rows of their own.
# Groups and single files are paged together, newest first.

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QModelIndex, QObject, QPersistentModelIndex, QTimer, Signal, Slot

from gfgmd.core.naming import format_label, group_of
from gfgmd.core.sources import source_from_url
from gfgmd.models.list_model import DictListModel
from gfgmd.services.context import AppContext
from gfgmd.services.recycle import recycle_media
from gfgmd.utils.format import format_bytes, format_duration, media_noun
from gfgmd.utils.logging import write_log

PAGE = 100
# The most files the players get as a playlist from the library (newest first).
PLAYLIST_LIMIT = 500
ROLES = ("rowKey", "rowType", "historyId", "groupKey", "title", "uploader", "site", "kind", "path", "fileName",
         "sizeText", "dateText", "durationText", "qualityText", "url", "missing", "thumbnail", "format", "number",
         "countText", "fileCount", "expanded", "inGroup")
_BLANK: dict[str, Any] = {
    "rowKey": "", "rowType": "file", "historyId": 0, "groupKey": "", "title": "", "uploader": "", "site": "",
    "kind": "video", "path": "", "fileName": "", "sizeText": "", "dateText": "", "durationText": "",
    "qualityText": "", "url": "", "missing": False, "thumbnail": "", "format": "", "number": 0, "countText": "",
    "fileCount": 0, "expanded": False, "inGroup": False,
}

_Index = QModelIndex | QPersistentModelIndex


def _date(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d %b %Y, %H:%M")


def _row(record: dict[str, Any], site_label: str, group_key: str = "", number: int = 0) -> dict[str, Any]:
    """One file's row; `group_key` is set (with its place, `number`) for a file shown inside its group."""
    path = record["filepath"]
    return {
        **_BLANK,
        "rowKey": f"f:{record['id']}", "rowType": "file", "historyId": record["id"], "groupKey": group_key,
        "title": record["title"] or Path(path).stem, "uploader": record["uploader"], "site": site_label,
        "kind": record["kind"], "path": path, "fileName": Path(path).name,
        "sizeText": format_bytes(record["size"]) if record["size"] else "",
        "dateText": _date(record["finished"]),
        "durationText": format_duration(record["duration"]) if record["duration"] else "",
        "qualityText": f"{record['height']}p" if record["height"] else "",
        "url": record["url"], "missing": not os.path.exists(path), "thumbnail": record["thumbnail"],
        "format": format_label(path), "number": number, "inGroup": bool(group_key),
    }


def _group_row(key: str, records: list[dict[str, Any]], site_label: str, expanded: bool) -> dict[str, Any]:
    """A playlist or channel folder's row: its name, how many songs and videos, and its newest cover."""
    newest = max(records, key=lambda record: record["finished"])
    songs = sum(1 for record in records if record["kind"] == "audio")
    videos = len(records) - songs
    counts = [f"{n} {media_noun(kind, n)}" for n, kind in ((songs, "audio"), (videos, "video")) if n]
    return {
        **_BLANK,
        "rowKey": f"g:{key}", "rowType": "group", "groupKey": key,
        "title": next((str(record["group_title"]) for record in records if record["group_title"]), "Playlist"),
        "site": site_label, "kind": "audio" if songs and not videos else "video",
        "path": str(Path(newest["filepath"]).parent), "thumbnail": newest["thumbnail"],
        "dateText": _date(newest["finished"]), "countText": " and ".join(counts), "fileCount": len(records),
        "expanded": expanded,
    }


class HistoryModel(DictListModel):
    """The Library's rows, newest first, loaded a page of groups and single files at a time."""

    def __init__(self, context: AppContext, parent: Any = None) -> None:
        super().__init__(ROLES, "rowKey", parent)
        self._context = context
        self._query = ""
        self._kind = ""
        self._site = ""
        self._total = 0
        self._units_total = 0
        self._units: list[dict[str, Any]] = []
        # Groups the user opened (or closed, while a search opens every group with a match).
        self._opened: set[str] = set()
        self._closed: set[str] = set()

    def set_filters(self, query: str, kind: str, site: str) -> None:
        self._query, self._kind, self._site = query, kind, site
        self._closed.clear()
        self.reload()

    def reload(self) -> None:
        """Start again from the newest row."""
        store = self._context.store
        self._total = store.history_count(self._query, self._kind, self._site)
        self._units_total = store.history_unit_count(self._query, self._kind, self._site)
        self._units = store.history_units(self._query, self._kind, self._site, 0, PAGE)
        self.reset(self._rows_for(self._units))

    def is_open(self, key: str) -> bool:
        """True when a group shows its files: opened by the user, or holding a search match."""
        if key in self._closed:
            return False
        return key in self._opened or bool(self._query)

    def set_open(self, key: str, opened: bool) -> None:
        """Show or hide a group's files."""
        (self._opened.add if opened else self._opened.discard)(key)
        (self._closed.discard if opened else self._closed.add)(key)
        self.sync(self._rows_for(self._units))

    def group_records(self, key: str) -> list[dict[str, Any]]:
        """A group's files the filters show, in playlist order."""
        return self._context.store.group_history(key, self._query, self._kind, self._site)

    def _rows_for(self, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
        store = self._context.store
        rows: list[dict[str, Any]] = []
        for unit in units:
            key = str(unit["group_key"] or "")
            if str(unit["unit"]).startswith("f:") or not key:
                record = store.history_record(int(unit["first_id"]))
                if record is not None:
                    rows.append(_row(record, self._label(record)))
                continue
            records = self.group_records(key)
            if not records:
                continue
            opened = self.is_open(key)
            rows.append(_group_row(key, records, self._label(records[0]), opened))
            if opened:
                rows += [_row(record, self._label(record), key, record["position"] or number)
                         for number, record in enumerate(records, start=1)]
        return rows

    def _label(self, record: dict[str, Any]) -> str:
        return self._context.site(record["site"]).label if record["site"] else ""

    @property
    def total(self) -> int:
        """How many files the filters match (a group's files each count)."""
        return self._total

    def canFetchMore(self, parent: _Index = QModelIndex()) -> bool:  # noqa: B008 - Qt's default argument
        return not parent.isValid() and len(self._units) < self._units_total

    def fetchMore(self, parent: _Index = QModelIndex()) -> None:  # noqa: B008 - Qt's default argument
        if parent.isValid():
            return
        more = self._context.store.history_units(self._query, self._kind, self._site, len(self._units), PAGE)
        self._units += more
        self.append(self._rows_for(more))


class LibraryController(QObject):
    """The Library page."""

    changed = Signal()
    notice = Signal(str)
    # A finished file should be downloaded again (link).
    # Download again on a file: its link, "audio" or "video", and its file type ("mp3", "mkv").
    redownloadRequested = Signal(str, str, str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._fill_groups()
        self._model = HistoryModel(context, self)
        self._query = ""
        self._kind = ""
        self._site = ""
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self.reload)
        self._model.reload()

    def _fill_groups(self) -> None:
        """Work out the playlist or channel folder of files saved before the Library grouped them.

        A file in a folder under its download (the job's, or today's video or audio folder) belongs to
        that folder's group; one in the download folder itself, or elsewhere, stands alone.
        """
        store = self._context.store
        records = store.history_without_group()
        if not records:
            return
        roots = [self._context.download_root("video"), self._context.download_root("audio")]
        groups: list[tuple[int, str, str]] = []
        for record in records:
            path = Path(record["filepath"])
            job = store.job(record["job_id"]) if record["job_id"] else None
            candidates = ([Path(job["output_root"])] if job is not None else []) + roots
            root = next((candidate for candidate in candidates if _inside(path, candidate)), None)
            key, title = group_of(path, root)
            groups.append((int(record["id"]), key, title))
        try:
            store.set_history_groups(groups)
        except sqlite3.Error as error:  # a library that can't be written still shows its files
            write_log(f"Library groups couldn't be saved: {error}", "critical")

    @Property(QObject, constant=True)
    def model(self) -> HistoryModel:
        return self._model

    @Property(int, notify=changed)
    def total(self) -> int:
        """How many files match the filters."""
        return self._model.total

    @Property(list, notify=changed)
    def siteOptions(self) -> list[dict[str, str]]:
        options = [{"label": "All sites", "code": ""}]
        for site in self._context.store.history_sites():
            options.append({"label": self._context.site(site).label, "code": site})
        return options

    @Slot(str, str, str)
    def setFilters(self, query: str, kind: str, site: str) -> None:
        """Show files matching the search text, type (video, audio), and site."""
        self._query, self._kind, self._site = query.strip(), kind, site
        self._model.set_filters(self._query, self._kind, self._site)
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        self._fill_groups()
        self._model.reload()
        self.changed.emit()

    def file_saved(self, _history_id: int, _path: str) -> None:
        """A download finished: refresh shortly (several files often finish together)."""
        self._reload_timer.start()

    def _record(self, history_id: int) -> dict[str, Any] | None:
        record = self._context.store.history_record(int(history_id))
        return _row(record, "") if record is not None else None

    @Slot(str, bool)
    def setExpanded(self, group_key: str, expanded: bool) -> None:
        """Show or hide a playlist's or channel's files under it."""
        self._model.set_open(group_key, expanded)

    @Slot(str, result="QVariantList")
    def groupIds(self, group_key: str) -> list[int]:
        """A group's files the filters show (picking the group picks them)."""
        return [int(record["id"]) for record in self._model.group_records(group_key)]

    @Slot(str, result="QVariantList")
    def groupPaths(self, group_key: str) -> list[str]:
        """A group's files that are still there, in playlist order (Play all)."""
        return [record["filepath"] for record in self._model.group_records(group_key)
                if os.path.isfile(record["filepath"])]

    @Slot(result=list)
    def playlist(self) -> list[str]:
        """The files the filters show that are still there, newest first, for the players' Previous and Next."""
        records = self._context.store.history(self._query, self._kind, self._site, 0, PLAYLIST_LIMIT)
        return [record["filepath"] for record in records if os.path.isfile(record["filepath"])]

    @Slot(result="QVariantList")
    def allIds(self) -> list[int]:
        """Every file the filters show, loaded into the list yet or not (Select all)."""
        return self._context.store.history_ids(self._query, self._kind, self._site)

    @Slot("QVariantList", result="QVariantList")
    def pathsOf(self, history_ids: list[int]) -> list[str]:
        """These files that are still there, newest first as the list shows them (Play the selection)."""
        wanted = {int(item) for item in history_ids}
        records = [self._context.store.history_record(history_id) for history_id in wanted]
        present = [record for record in records if record is not None and os.path.isfile(record["filepath"])]
        present.sort(key=lambda record: (record["finished"], record["id"]), reverse=True)
        return [record["filepath"] for record in present]

    @Slot(int, result=str)
    def pathOf(self, history_id: int) -> str:
        record = self._record(history_id)
        return record["path"] if record else ""

    @Slot(int)
    def redownload(self, history_id: int) -> None:
        """Queue the file's link again."""
        record = self._record(history_id)
        if not record or not record["url"]:
            self.notice.emit("This file has no link to download it from.")
            return
        try:
            source_from_url(record["url"])
        except ValueError as error:
            self.notice.emit(str(error))
            return
        self.redownloadRequested.emit(record["url"], record["kind"], Path(record["path"]).suffix[1:].lower())

    @Slot("QVariantList")
    def remove(self, history_ids: list[int]) -> None:
        """Take files off the list (the files stay on disk)."""
        self._context.store.delete_history(int(item) for item in history_ids)
        self.reload()

    @Slot("QVariantList")
    def deleteFiles(self, history_ids: list[int]) -> None:
        """Move files (with their captions, lyrics, and covers) to the Recycle Bin and take them off the list."""
        records = [self._record(int(item)) for item in history_ids]
        paths = [record["path"] for record in records if record and not record["missing"]]
        if not recycle_media(paths):
            self.notice.emit("Windows couldn't move the files to the Recycle Bin; they may be open in a player.")
            return
        self._context.store.delete_history(int(item) for item in history_ids)
        self.notice.emit(f"Moved {len(paths)} file{'s' if len(paths) != 1 else ''} to the Recycle Bin.")
        self.reload()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
