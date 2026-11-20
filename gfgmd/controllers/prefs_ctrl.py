# prefs_ctrl.py - preferences (settings) controller
#
# A thin surface over settings.json. QML reads any value with value("section.key"), binding to
# `revision` so it re-reads after every save; saveSettings applies dotted-key updates in one write.
# settingsChanged lets the app re-apply side effects (Start with Windows, the queue's limits); this
# controller never performs those itself. It also runs "Optimize for this PC" for Parts at once.

from __future__ import annotations

import os
import threading
import time
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.config.defaults import (
    DownloadDefaults,
    FormatDefaults,
    LoggingDefaults,
    PresetDefaults,
    ScheduleDefaults,
    ThemeDefaults,
    ToolDefaults,
)
from gfgmd.core.benchmark import measure, pick_fastest
from gfgmd.core.sources import source_from_url
from gfgmd.services.context import AppContext
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.format import format_bytes
from gfgmd.utils.logging import clear_logs, get_logs_dir, write_log
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings

_NOT_SAVED = "Couldn't save your preferences, so the previous ones are still in use."


def _options(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [{"label": label, "code": code} for label, code in pairs]


def all_presets(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Built-in presets followed by the user's own."""
    return [*PresetDefaults.BUILT_IN, *settings.get("presets", [])]


class PrefsController(QObject):
    """Exposes application preferences to QML."""

    settingsChanged = Signal()
    themeChanged = Signal(str)
    saveFinished = Signal(bool, str)
    optimizeChanged = Signal()
    optimizeFinished = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._settings = load_settings()
        self._revision = 0
        self._runner = TaskRunner(1, self)
        self._optimizing = False
        self._optimize_step = (0, 0)
        self._optimize_stop = threading.Event()
        # The test reports its steps from a worker thread; this timer republishes them on the GUI thread.
        self._optimize_timer = QTimer(self)
        self._optimize_timer.setInterval(500)
        self._optimize_timer.timeout.connect(self.optimizeChanged)

    # ── Reading ───────────────────────────────────────────────────────────

    def _get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self._settings
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @Property(int, notify=settingsChanged)
    def revision(self) -> int:
        """Bumped after every save, so bindings that call value() read again."""
        return self._revision

    @Slot(str, result="QVariant")
    def value(self, key: str) -> Any:
        """One setting by dotted key, such as "downloads.concurrent"."""
        return self._get(*key.split("."))

    @Property(str, notify=themeChanged)
    def theme(self) -> str:
        return self._get("theme", default=ThemeDefaults.DEFAULT_THEME)

    @Property(bool, notify=settingsChanged)
    def closeToTray(self) -> bool:
        return bool(self._get("tray", "close_to_tray", default=True))

    @Property(str, notify=settingsChanged)
    def downloadFolder(self) -> str:
        """The folder video downloads go to, as a path (the default folder when none is chosen)."""
        return str(self._context.download_root())

    @Property(list, constant=True)
    def losslessAudio(self) -> list[str]:
        """Audio formats without a bitrate to choose (FLAC, WAV, the original stream)."""
        return list(FormatDefaults.LOSSLESS_AUDIO)

    @Property(str, notify=settingsChanged)
    def audioFolder(self) -> str:
        """The folder audio downloads go to, as a path (Music\\gfgRoyal Media Downloader by default)."""
        return str(self._context.download_root("audio"))

    @Property(bool, notify=settingsChanged)
    def autoCheckUpdates(self) -> bool:
        return bool(self._get("updates", "auto_check", default=True))

    @Property(bool, notify=settingsChanged)
    def autoInstallUpdates(self) -> bool:
        return bool(self._get("updates", "auto_install", default=True))

    @Property(dict, constant=True)
    def options(self) -> dict[str, Any]:
        """{label, code} lists for every combo box."""
        return {
            "theme": _options(ThemeDefaults.OPTIONS),
            "logLevel": _options(LoggingDefaults.OPTIONS),
            "height": _options(FormatDefaults.HEIGHT_OPTIONS),
            "container": _options(FormatDefaults.CONTAINER_OPTIONS),
            "codec": _options(FormatDefaults.CODEC_OPTIONS),
            "audio": _options(FormatDefaults.AUDIO_OPTIONS),
            "audioQuality": _options(FormatDefaults.AUDIO_QUALITY_OPTIONS),
            "audioTracks": _options(FormatDefaults.AUDIO_TRACK_OPTIONS),
            "cover": _options(FormatDefaults.COVER_OPTIONS),
            "subtitles": _options(FormatDefaults.SUBTITLE_OPTIONS),
            "subtitleFormat": _options(FormatDefaults.SUBTITLE_FORMAT_OPTIONS),
            "sponsorblock": _options(FormatDefaults.SPONSORBLOCK_OPTIONS),
            "sponsorCategories": _options(FormatDefaults.SPONSORBLOCK_CATEGORIES),
            "filename": _options(DownloadDefaults.FILENAME_OPTIONS),
            "concurrent": _options(DownloadDefaults.CONCURRENT_OPTIONS),
            "fragments": _options(DownloadDefaults.FRAGMENT_OPTIONS),
            "whenDone": _options(ScheduleDefaults.WHEN_DONE_OPTIONS),
            "interval": _options(ScheduleDefaults.INTERVAL_OPTIONS),
            "toolSource": _options(ToolDefaults.SOURCE_OPTIONS),
            "toolChannel": _options(ToolDefaults.CHANNEL_OPTIONS),
            "kind": [{"label": "Video", "code": "video"}, {"label": "Audio only", "code": "audio"}],
        }

    @Property(list, notify=settingsChanged)
    def presets(self) -> list[dict[str, Any]]:
        """Download presets as {label, code} for the preset box, built-in first."""
        return [{"label": preset["label"], "code": preset["id"]} for preset in all_presets(self._settings)]

    @Slot(str, result="QVariantMap")
    def preset(self, preset_id: str) -> dict[str, Any]:
        """One preset's values ({} when it no longer exists)."""
        return next((dict(p) for p in all_presets(self._settings) if p["id"] == preset_id), {})

    # ── Writing ───────────────────────────────────────────────────────────

    def _set(self, value: Any, *keys: str) -> None:
        node = self._settings
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    @Slot("QVariantMap")
    def saveSettings(self, updates: dict[str, Any]) -> None:
        """Apply dotted-key updates (e.g. {"downloads.concurrent": 2}) and save in one write."""
        theme_before = self._get("theme")
        self._settings = load_settings()  # another window may have saved since
        for key, value in updates.items():
            self._set(value, *key.split("."))
        self._persist()
        if self._get("theme") != theme_before:
            self.themeChanged.emit(self._get("theme", default=ThemeDefaults.DEFAULT_THEME))

    @Slot("QVariantMap", result=str)
    def savePreset(self, values: dict[str, Any]) -> str:
        """Save the current choices as a named preset; returns its id ("" if it couldn't be saved)."""
        label = str(values.get("label", "")).strip()[:80]
        if not label:
            return ""
        preset = {"id": f"user-{int(time.time() * 1000)}", "label": label}
        for key in ("kind", "max_height", "container", "codec_profile", "audio_tracks", "audio_langs", "audio_format",
                    "audio_quality", "cover", "subtitles", "subtitle_format", "sponsorblock", "lyrics"):
            if key in values:
                preset[key] = values[key]
        presets = [*self._get("presets", default=[]), preset]
        self.saveSettings({"presets": presets})
        saved = any(p.get("id") == preset["id"] for p in self._get("presets", default=[]))
        return preset["id"] if saved else ""

    @Slot(str)
    def deletePreset(self, preset_id: str) -> None:
        """Remove a saved preset (built-in presets stay)."""
        presets = [p for p in self._get("presets", default=[]) if p.get("id") != preset_id]
        updates: dict[str, Any] = {"presets": presets}
        if self._get("downloads", "preset") == preset_id:
            updates["downloads.preset"] = PresetDefaults.DEFAULT
        self.saveSettings(updates)

    @Slot()
    def resetDefaults(self) -> None:
        """Reset all settings to factory defaults (saved presets are kept)."""
        presets = self._get("presets", default=[])
        self._settings = get_default_settings()
        self._settings["presets"] = presets
        self._persist()
        self.themeChanged.emit(self._get("theme", default=ThemeDefaults.DEFAULT_THEME))

    def _persist(self) -> bool:
        saved = save_settings(self._settings)
        if saved:
            self.saveFinished.emit(True, "")
        else:
            write_log("Could not save settings", "critical")
            self.saveFinished.emit(False, _NOT_SAVED)
        # Reload what is on disk: invalid values were dropped, and a failed save keeps the old file.
        self._settings = load_settings()
        self._revision += 1
        self.settingsChanged.emit()
        return saved

    @Slot()
    def clearLogs(self) -> None:
        """Empty the log files."""
        if clear_logs():
            self.saveFinished.emit(True, "Logs cleared.")
        else:
            self.saveFinished.emit(False, "Couldn't clear the log files; they may be open in another program.")

    @Slot()
    def openLogsFolder(self) -> None:
        """Open the logs folder in File Explorer."""
        try:
            os.startfile(get_logs_dir())  # type: ignore[attr-defined]
        except OSError as error:
            write_log(f"Could not open the logs folder: {error}", "critical")
            self.saveFinished.emit(False, "Couldn't open the logs folder.")

    # ── Optimize for this PC ──────────────────────────────────────────────

    @Property(bool, notify=optimizeChanged)
    def optimizing(self) -> bool:
        return self._optimizing

    @Property(float, notify=optimizeChanged)
    def optimizeProgress(self) -> float:
        done, total = self._optimize_step
        return done / total if total else 0.0

    @Slot(str)
    def startOptimize(self, url: str) -> None:
        """Measure 4, 8, and 16 parts at once on a video, then keep the fastest as the Parts at once setting."""
        if self._optimizing:
            return
        try:
            source_from_url(url)
        except ValueError as error:
            write_log(f"The speed test link was refused: {error}", "general")
            self.optimizeFinished.emit("Paste a link to one video to test with.")
            return
        try:
            tools = self._context.tools()
        except RuntimeError as error:
            write_log(f"The speed test couldn't find the download tools: {error}", "critical")
            self.optimizeFinished.emit("The download tools aren't installed yet. Get them in the Tools section.")
            return
        self._optimizing = True
        self._optimize_step = (0, 0)
        self._optimize_stop.clear()
        self._optimize_timer.start()
        self.optimizeChanged.emit()

        def report(done: int, total: int) -> None:
            self._optimize_step = (done, total)  # read by the progress property on the GUI thread

        self._runner.start(measure, url.strip(), tools, self._context.cache_dir, self._optimize_stop, 6.0, report,
                           on_done=self._optimized, on_error=self._optimize_failed)

    @Slot()
    def cancelOptimize(self) -> None:
        self._optimize_stop.set()

    def _optimized(self, speeds: dict[int, float]) -> None:
        self._optimizing = False
        self._optimize_timer.stop()
        self.optimizeChanged.emit()
        if self._optimize_stop.is_set() or not speeds or max(speeds.values()) <= 0:
            self.optimizeFinished.emit("The speed test stopped before it could measure anything.")
            return
        best = pick_fastest(speeds, DownloadDefaults.AUTO_FRAGMENTS)
        summary = ", ".join(f"{count} parts: {format_bytes(int(speed))}/s" for count, speed in sorted(speeds.items()))
        self.saveSettings({"downloads.fragments": 0 if best == DownloadDefaults.AUTO_FRAGMENTS else best})
        self.optimizeFinished.emit(f"Fastest here: {best} parts at once ({summary}). Saved.")

    def _optimize_failed(self, _message: str) -> None:
        """The test raised; the task runner has logged why, so the user gets what to do instead."""
        self._optimizing = False
        self._optimize_timer.stop()
        self.optimizeChanged.emit()
        self.optimizeFinished.emit("The speed test couldn't finish. Check the link and your internet connection, "
                                   "then try again.")

    def shutdown(self) -> None:
        self._optimize_stop.set()
        self._runner.shutdown(3000)
