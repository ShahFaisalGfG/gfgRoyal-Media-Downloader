# notifier.py - desktop notifications from the app's tray icon
#
# The app keeps a tray icon while it runs (it closes to the tray), so notifications use that icon.
# Clicking a notification brings the window forward, or shows the saved file when one is attached.

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QSystemTrayIcon

from gfgmd.config.defaults import AppInfo
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings, save_settings

SHOW_MS = 10_000


class Notifier(QObject):
    """Shows tray messages; the latest message decides what a click does."""

    def __init__(self, show_window: Callable[[], None], reveal: Callable[[str], object],
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray: QSystemTrayIcon | None = None
        self._show_window = show_window
        self._reveal = reveal
        self._path = ""

    def attach(self, tray: QSystemTrayIcon | None) -> None:
        """Use this tray icon (None when the system has no tray)."""
        self._tray = tray
        if tray is not None:
            tray.messageClicked.connect(self._clicked)

    def tell_once_in_tray(self) -> None:
        """The first time the window closes to the tray, say the app goes on running there."""
        settings = load_settings()
        tray = settings.setdefault("tray", {})
        if tray.get("told_running") or not settings.get("notifications", {}).get("enabled", True):
            return
        tray["told_running"] = True
        save_settings(settings)
        self.notify(f"{AppInfo.APP_NAME} is still running",
                    "Downloads and subscription checks go on in the tray. Right-click its icon to quit.")

    def notify(self, title: str, body: str, path: str = "") -> None:
        """Show a message; `path` is revealed in File Explorer when the message is clicked."""
        if self._tray is None or not QSystemTrayIcon.supportsMessages():
            write_log(f"Notification not shown (no tray): {title}: {body}", "general")
            return
        self._path = path
        self._tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, SHOW_MS)

    def _clicked(self) -> None:
        if self._path:
            self._reveal(self._path)
        else:
            self._show_window()
