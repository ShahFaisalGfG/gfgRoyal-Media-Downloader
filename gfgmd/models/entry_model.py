# entry_model.py - a playlist's or channel's entries with check boxes, for choosing what to download
#
# Holds every entry; a text filter shows a subset while the choices of hidden entries are kept.

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import Property, Signal, Slot

from gfgmd.core.analyze import Entry
from gfgmd.models.list_model import DictListModel
from gfgmd.utils.format import format_duration

ROLES = ("entryId", "title", "position", "durationText", "checked", "archived", "unavailable", "thumbnail")
_UNAVAILABLE = {"private", "needs_auth", "subscriber_only", "premium_only"}


class EntryModel(DictListModel):
    """Entries with check boxes; `selectedCount` counts checked entries, visible or not."""

    selectionChanged = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(ROLES, "entryId", parent)
        self._entries: list[Entry] = []
        self._checked: dict[str, bool] = {}
        self._archived: set[str] = set()
        self._filter = ""

    def load(self, entries: Iterable[Entry], archived: set[str]) -> None:
        """Show a new list; everything not already downloaded starts checked."""
        self._entries = list(entries)
        self._archived = archived
        self._checked = {entry.id: entry.id not in archived and entry.availability not in _UNAVAILABLE
                         for entry in self._entries}
        self._filter = ""
        self._show()

    def set_archived(self, archived: set[str]) -> None:
        """Mark entries already downloaded with the chosen format."""
        self._archived = archived
        for entry in self._entries:
            self.update(entry.id, {"archived": entry.id in archived})

    def _row(self, entry: Entry) -> dict[str, Any]:
        return {
            "entryId": entry.id, "title": entry.title, "position": entry.index,
            "durationText": format_duration(entry.duration) if entry.duration else "",
            "checked": self._checked.get(entry.id, False), "archived": entry.id in self._archived,
            "unavailable": entry.availability in _UNAVAILABLE, "thumbnail": entry.thumbnail,
        }

    def _show(self) -> None:
        text = self._filter.casefold()
        self.reset(self._row(entry) for entry in self._entries if not text or text in entry.title.casefold())
        self.selectionChanged.emit()

    @Property(int, notify=selectionChanged)
    def selectedCount(self) -> int:
        return sum(1 for checked in self._checked.values() if checked)

    @Property(int, notify=selectionChanged)
    def totalCount(self) -> int:
        return len(self._entries)

    @Property(str, notify=selectionChanged)
    def selectedDuration(self) -> str:
        total = sum(entry.duration for entry in self._entries if self._checked.get(entry.id))
        return format_duration(total) if total else ""

    @Slot(str)
    def setFilter(self, text: str) -> None:
        """Show only entries whose titles contain text."""
        self._filter = text.strip()
        self._show()

    @Slot(int)
    def toggle(self, row: int) -> None:
        values = self.get(row)
        if values:
            self._checked[values["entryId"]] = not values["checked"]
            self.update(values["entryId"], {"checked": not values["checked"]})
            self.selectionChanged.emit()

    @Slot(bool)
    def checkVisible(self, checked: bool) -> None:
        """Check or clear every entry the filter shows."""
        for values in self.rows():
            self._checked[values["entryId"]] = checked
            self.update(values["entryId"], {"checked": checked})
        self.selectionChanged.emit()

    @Slot()
    def checkNew(self) -> None:
        """Check only the entries not downloaded before."""
        for entry in self._entries:
            self._checked[entry.id] = entry.id not in self._archived and entry.availability not in _UNAVAILABLE
            self.update(entry.id, {"checked": self._checked[entry.id]})
        self.selectionChanged.emit()

    @Slot(int, int)
    def checkRange(self, first: int, last: int) -> None:
        """Check the entries numbered first to last (playlist positions) and clear the rest."""
        low, high = min(first, last), max(first, last)
        for entry in self._entries:
            self._checked[entry.id] = low <= entry.index <= high
            self.update(entry.id, {"checked": self._checked[entry.id]})
        self.selectionChanged.emit()

    def selected(self) -> list[Entry]:
        """The checked entries in playlist order."""
        return [entry for entry in self._entries if self._checked.get(entry.id)]

    def all_selected(self) -> bool:
        return all(self._checked.get(entry.id) for entry in self._entries)
