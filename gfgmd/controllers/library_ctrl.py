# library_ctrl.py - finished downloads: search, filters, paging, and actions on files

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QModelIndex, QObject, QPersistentModelIndex, QTimer, Signal, Slot

from gfgmd.core.naming import format_label
from gfgmd.core.sources import source_from_url
from gfgmd.models.list_model import DictListModel
from gfgmd.services.context import AppContext
from gfgmd.services.recycle import recycle_media
from gfgmd.utils.format import format_bytes, format_duration

PAGE = 100
# The most files the players get as a playlist from the library (newest first).
PLAYLIST_LIMIT = 500
ROLES = ("historyId", "title", "uploader", "site", "kind", "path", "fileName", "sizeText", "dateText",
         "durationText", "qualityText", "url", "missing", "thumbnail", "format")

_Index = QModelIndex | QPersistentModelIndex


def _row(record: dict[str, Any], site_label: str) -> dict[str, Any]:
    path = record["filepath"]
    return {
        "historyId": record["id"], "title": record["title"] or Path(path).stem, "uploader": record["uploader"],
        "site": site_label, "kind": record["kind"], "path": path, "fileName": Path(path).name,
        "sizeText": format_bytes(record["size"]) if record["size"] else "",
        "dateText": datetime.fromtimestamp(record["finished"]).strftime("%d %b %Y, %H:%M"),
        "durationText": format_duration(record["duration"]) if record["duration"] else "",
        "qualityText": f"{record['height']}p" if record["height"] else "",
        "url": record["url"], "missing": not os.path.exists(path), "thumbnail": record["thumbnail"],
        "format": format_label(path),
    }


class HistoryModel(DictListModel):
    """Finished files, newest first, loaded a page at a time as the list scrolls."""

    def __init__(self, context: AppContext, parent: Any = None) -> None:
        super().__init__(ROLES, "historyId", parent)
        self._context = context
        self._query = ""
        self._kind = ""
        self._site = ""
        self._total = 0

    def set_filters(self, query: str, kind: str, site: str) -> None:
        self._query, self._kind, self._site = query, kind, site
        self.reload()

    def reload(self) -> None:
        """Start again from the newest file."""
        store = self._context.store
        self._total = store.history_count(self._query, self._kind, self._site)
        self.reset(self._rows_at(0))

    def _rows_at(self, offset: int) -> list[dict[str, Any]]:
        records = self._context.store.history(self._query, self._kind, self._site, offset, PAGE)
        return [_row(record, self._context.site(record["site"]).label if record["site"] else "") for record in records]

    @property
    def total(self) -> int:
        return self._total

    def canFetchMore(self, parent: _Index = QModelIndex()) -> bool:  # noqa: B008 - Qt's default argument
        return not parent.isValid() and self.rowCount() < self._total

    def fetchMore(self, parent: _Index = QModelIndex()) -> None:  # noqa: B008 - Qt's default argument
        if not parent.isValid():
            self.append(self._rows_at(self.rowCount()))


class LibraryController(QObject):
    """The Library page."""

    changed = Signal()
    notice = Signal(str)
    # A finished file should be downloaded again (link).
    redownloadRequested = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._model = HistoryModel(context, self)
        self._query = ""
        self._kind = ""
        self._site = ""
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(800)
        self._reload_timer.timeout.connect(self.reload)
        self._model.reload()

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
        self._model.reload()
        self.changed.emit()

    def file_saved(self, _history_id: int, _path: str) -> None:
        """A download finished: refresh shortly (several files often finish together)."""
        self._reload_timer.start()

    def _record(self, history_id: int) -> dict[str, Any] | None:
        row = self._model.row_of(history_id)
        return self._model.get(row) if row >= 0 else None

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
        self.redownloadRequested.emit(record["url"])

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
        self.notice.emit(f"Moved {len(paths)} file(s) to the Recycle Bin.")
        self.reload()
