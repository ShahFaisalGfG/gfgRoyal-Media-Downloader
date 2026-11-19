# list_model.py - a dict-row list model for QML with keyed reconciliation and per-row updates
#
# Each model declares its role names; rows are plain dicts keyed by `key_field`. sync() reconciles
# a whole new list (removing, inserting, and updating only what changed, so QML keeps scroll
# position and delegates), and update() changes one row's values with a single dataChanged.

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt, Signal, Slot

_Index = QModelIndex | QPersistentModelIndex


class DictListModel(QAbstractListModel):
    """Rows of dicts exposed to QML under the declared role names."""

    countChanged = Signal()

    def __init__(self, roles: Iterable[str], key_field: str, parent: Any = None) -> None:
        super().__init__(parent)
        self._names = list(roles)
        self._roles = {Qt.ItemDataRole.UserRole + 1 + i: name.encode() for i, name in enumerate(self._names)}
        self._role_of = {name: role for role, name in ((r, n.decode()) for r, n in self._roles.items())}
        self._key = key_field
        self._rows: list[dict[str, Any]] = []
        self._index: dict[Any, int] = {}

    # ── Qt model interface ────────────────────────────────────────────────

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008 - Qt's default argument
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._roles.get(role)
        return self._rows[index.row()].get(name.decode()) if name is not None else None

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name) for role, name in self._roles.items()}

    @Property(int, notify=countChanged)
    def count(self) -> int:
        """How many rows the model holds."""
        return len(self._rows)

    @Slot(int, result="QVariantMap")
    def get(self, row: int) -> dict[str, Any]:
        """One row's values ({} when out of range)."""
        return dict(self._rows[row]) if 0 <= row < len(self._rows) else {}

    # ── Python side ───────────────────────────────────────────────────────

    def rows(self) -> list[dict[str, Any]]:
        """A copy of every row."""
        return [dict(row) for row in self._rows]

    def row_of(self, key: Any) -> int:
        """The row index of a key, or -1."""
        return self._index.get(key, -1)

    def _reindex(self) -> None:
        self._index = {row[self._key]: i for i, row in enumerate(self._rows)}

    def reset(self, rows: Iterable[dict[str, Any]]) -> None:
        """Replace every row (for paged lists where order changes wholesale)."""
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self._reindex()
        self.endResetModel()
        self.countChanged.emit()

    def append(self, rows: Iterable[dict[str, Any]]) -> None:
        """Add rows at the end in one insert."""
        new = [dict(row) for row in rows if row[self._key] not in self._index]
        if not new:
            return
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(new) - 1)
        self._rows.extend(new)
        self._reindex()
        self.endInsertRows()
        self.countChanged.emit()

    def sync(self, rows: list[dict[str, Any]]) -> None:
        """Make the model match `rows` (same keys, same order), touching only what changed."""
        wanted = [row[self._key] for row in rows]
        keep = set(wanted)
        for i in range(len(self._rows) - 1, -1, -1):
            if self._rows[i][self._key] not in keep:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._rows[i]
                self.endRemoveRows()
        self._reindex()
        current = [row[self._key] for row in self._rows]
        if current != [key for key in wanted if key in self._index]:
            # The order changed (a job was moved): a reset is simplest and the queue is short.
            by_key = {row[self._key]: row for row in rows}
            self.reset(by_key[key] for key in wanted)
            return
        for position, row in enumerate(rows):
            key = row[self._key]
            if key not in self._index:
                self.beginInsertRows(QModelIndex(), position, position)
                self._rows.insert(position, dict(row))
                self.endInsertRows()
                self._reindex()
            else:
                self.update(key, row)
        self.countChanged.emit()

    def update(self, key: Any, values: dict[str, Any]) -> None:
        """Change some of one row's values."""
        row = self._index.get(key)
        if row is None:
            return
        current = self._rows[row]
        changed = [name for name, value in values.items() if current.get(name) != value]
        if not changed:
            return
        current.update(values)
        roles = [self._role_of[name] for name in changed if name in self._role_of]
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, roles)
