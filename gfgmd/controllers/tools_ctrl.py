# tools_ctrl.py - yt-dlp, FFmpeg, and Deno for QML: first-run setup, versions, updates, rollback

from __future__ import annotations

import os
import sys
import threading
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.core.tool_install import packages
from gfgmd.core.tools import TOOL_NAMES, path_tools
from gfgmd.services.tasks import TaskRunner
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.format import format_bytes
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings

# Look for tool updates this long after startup, then once a day while the app runs.
FIRST_CHECK_MS = 90_000
DAILY_MS = 24 * 3600 * 1000
_LABELS = {"yt-dlp": "yt-dlp", "ffmpeg": "FFmpeg", "ffprobe": "ffprobe", "deno": "Deno"}


class ToolsController(QObject):
    """The download tools' state and the setup and update actions."""

    changed = Signal()
    notice = Signal(str)
    # Tools were installed or the source changed, so downloads can start.
    toolsReady = Signal()

    def __init__(self, manager: ToolManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._runner = TaskRunner(1, self)
        self._rows: list[dict[str, Any]] = []
        self._missing = manager.missing()
        self._updates: list[str] = []
        self._busy = False
        self._stage = ""
        self._done = 0
        self._total = 0
        self._cancel = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.changed)
        self._daily = QTimer(self)
        self._daily.timeout.connect(self._auto_update)
        self._daily.start(FIRST_CHECK_MS)

    # ── Properties ────────────────────────────────────────────────────────

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        """True when every program can be found."""
        return not self._missing

    @Property(list, notify=changed)
    def missing(self) -> list[str]:
        return [_LABELS[name] for name in self._missing]

    @Property(bool, notify=changed)
    def canInstall(self) -> bool:
        """True where the app can download its own copies (Windows)."""
        return sys.platform == "win32"

    @Property(bool, notify=changed)
    def foundOnPath(self) -> bool:
        """True when every program is already on PATH (installed with winget, for example)."""
        return all(name in path_tools() for name in TOOL_NAMES)

    @Property(str, notify=changed)
    def downloadSize(self) -> str:
        """About how much the first-run download is."""
        return f"about {sum(package.approx_mb for package in packages()):,} MB"

    @Property(list, notify=changed)
    def rows(self) -> list[dict[str, Any]]:
        """Each program: label, version, where it comes from, and its path."""
        return [{**row, "label": _LABELS[row["name"]]} for row in self._rows]

    @Property(list, notify=changed)
    def updates(self) -> list[str]:
        return [_LABELS.get(name, name) for name in self._updates]

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=changed)
    def stage(self) -> str:
        if self._busy and self._total:
            return f"{self._stage}  ·  {format_bytes(self._done)} of {format_bytes(self._total)}"
        return self._stage

    @Property(float, notify=changed)
    def progress(self) -> float:
        return self._done / self._total if self._total else -1.0

    # ── Actions ───────────────────────────────────────────────────────────

    @Slot()
    def refresh(self) -> None:
        """Find each program and read its version in the background."""
        self._missing = self._manager.missing()
        self._runner.start(self._manager.status, on_done=self._set_rows)
        self.changed.emit()

    def _set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.changed.emit()

    @Slot()
    def installMissing(self) -> None:
        """Download the programs that are missing (all three on first run)."""
        self._install(self._manager.missing() or list(TOOL_NAMES))

    @Slot()
    def updateAll(self) -> None:
        """Install the newest yt-dlp, FFmpeg, and Deno."""
        self._install(list(TOOL_NAMES))

    @Slot(str)
    def update(self, tool: str) -> None:
        """Install the newest release of one program."""
        self._install([tool])

    def _install(self, names: list[str]) -> None:
        if self._busy:
            return
        self._busy = True
        self._cancel = threading.Event()
        self._stage, self._done, self._total = "Starting", 0, 0
        self._timer.start()
        self.changed.emit()
        self._runner.start(self._manager.install, names, self._report, self._cancel,
                           on_done=self._installed, on_error=self._install_failed)

    def _report(self, stage: str, done: int, total: int) -> None:
        # Called on the pool thread; the timer publishes these on the GUI thread.
        self._stage, self._done, self._total = stage, done, total

    def _installed(self, tools: list[str]) -> None:
        self._finish("Installed " + ", ".join(_LABELS.get(t, t) for t in tools) + ".")
        self._updates = [name for name in self._updates if name not in tools]
        self.toolsReady.emit()

    def _install_failed(self, message: str) -> None:
        self._finish(message)
        self.notice.emit(message)

    def _finish(self, stage: str) -> None:
        self._busy = False
        self._timer.stop()
        self._stage, self._done, self._total = stage, 0, 0
        self.refresh()

    @Slot()
    def cancel(self) -> None:
        """Stop an install; nothing changes until a package is complete and verified."""
        self._cancel.set()

    @Slot()
    def checkUpdates(self) -> None:
        """Ask GitHub whether newer releases exist (reads only the small checksum files)."""
        self._stage = "Checking for tool updates..."
        self.changed.emit()
        self._runner.start(self._manager.check_updates, on_done=self._checked,
                           on_error=lambda message: self._set_stage(f"Couldn't check: {message}"))

    def _checked(self, names: list[str]) -> None:
        self._updates = names
        self._set_stage("Updates available: " + ", ".join(_LABELS.get(n, n) for n in names) if names
                        else "Every managed tool is up to date.")

    def _set_stage(self, text: str) -> None:
        self._stage = text
        self.changed.emit()

    @Slot(str)
    def rollBack(self, tool: str) -> None:
        """Return a program to its previous version (when a new one misbehaves)."""
        if self._manager.roll_back(tool):
            self.notice.emit(f"{_LABELS.get(tool, tool)} is back to its previous version.")
            self.refresh()
        else:
            self.notice.emit("There is no previous version to go back to.")

    @Slot()
    def openFolder(self) -> None:
        """Open the managed tools' folder."""
        try:
            os.startfile(str(self._manager.tools_root))  # type: ignore[attr-defined]
        except OSError as error:
            write_log(f"Could not open the tools folder: {error}", "critical")

    def settings_changed(self) -> None:
        """The tool source or paths changed in Preferences."""
        was_missing = bool(self._missing)
        self.refresh()
        if was_missing and not self._missing:
            self.toolsReady.emit()

    def _auto_update(self) -> None:
        """Keep the managed tools current in the background (yt-dlp changes often)."""
        self._daily.start(DAILY_MS)
        prefs = load_settings().get("tools", {})
        if not prefs.get("auto_update", True) or prefs.get("source", "managed") != "managed" or self._busy:
            return
        self._runner.start(self._manager.check_updates, on_done=self._auto_install)

    def _auto_install(self, names: list[str]) -> None:
        self._updates = names
        if names:
            write_log("Updating tools: " + ", ".join(names), "general")
            self._install(names)

    def shutdown(self) -> None:
        self._cancel.set()
        self._daily.stop()
        self._runner.shutdown(3000)

