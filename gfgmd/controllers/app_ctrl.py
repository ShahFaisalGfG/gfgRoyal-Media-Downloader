# app_ctrl.py - app-wide controller: theme, app information, screens, files, and the clipboard

from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtCore import Property, QObject, QPoint, QRect, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from gfgmd.config.defaults import AppInfo
from gfgmd.core.sources import as_link, check_url
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings, take_read_error

if sys.platform == "win32":
    import winreg

_SETTINGS_RESET = "Your preferences file couldn't be read, so the defaults are in use."


def _detect_system_theme() -> str:
    """Read the Windows registry to decide light or dark mode."""
    if sys.platform != "win32":
        return "light"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value == 1 else "dark"
    except OSError:
        return "light"


def select_in_explorer(path: str) -> bool:
    """Open the file's folder in File Explorer with the file selected; True on success."""
    if sys.platform != "win32" or not os.path.exists(path):
        return False
    shell32 = ctypes.windll.shell32
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
    item = shell32.ILCreateFromPathW(os.path.abspath(path))
    if not item:
        return False
    try:
        return shell32.SHOpenFolderAndSelectItems(item, 0, None, 0) == 0
    finally:
        shell32.ILFree(item)


def open_path(path: str) -> bool:
    """Open a file or folder with its default program."""
    if not path or not os.path.exists(path):
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class AppController(QObject):
    """Exposes app-wide state and actions to QML."""

    themeChanged = Signal(str)
    # A start-up or background message for the user; the window shows it as a toast.
    notice = Signal(str)
    # A downloadable link was copied (Preferences > Watch the clipboard); the window offers it.
    clipboardLink = Signal(str)
    # Emitted by the window when closing it left the app running in the tray.
    closedToTray = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        raw = load_settings().get("theme", "system")
        self._theme = _detect_system_theme() if raw == "system" else raw
        self._preview = ""

    # ── Properties ──────────────────────────────────────────────────────────

    @Property(str, notify=themeChanged)
    def currentTheme(self) -> str:
        """The resolved theme name ("light" or "dark")."""
        return self._theme

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return AppInfo.APP_VERSION

    @Property(str, constant=True)
    def appName(self) -> str:
        return AppInfo.APP_NAME

    @Property(str, constant=True)
    def appDescription(self) -> str:
        return AppInfo.APP_DESCRIPTION

    @Property(str, constant=True)
    def appAuthor(self) -> str:
        return AppInfo.APP_AUTHOR

    @Property(bool, constant=True)
    def trayAvailable(self) -> bool:
        """True when a system tray exists, so the window can close to it."""
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ── Slots ──────────────────────────────────────────────────────────────

    @Slot()
    def detectTheme(self) -> None:
        """Re-detect the theme (when a window regains focus) and emit themeChanged if it changed."""
        raw = self._preview or load_settings().get("theme", "system")
        self._set_theme(_detect_system_theme() if raw == "system" else raw)

    @Slot(str)
    def previewTheme(self, theme: str) -> None:
        """Show a theme choice while Preferences is open."""
        self._preview = theme
        self.detectTheme()

    @Slot()
    def endPreview(self) -> None:
        """Go back to the saved theme after Preferences closes."""
        self._preview = ""
        self.detectTheme()

    @Slot(int, int, result=QRect)
    def availableGeometry(self, x: int, y: int) -> QRect:
        """The area windows may use (no taskbar) on the screen at (x, y), else the primary screen."""
        screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    @Slot(str, result=bool)
    def openPath(self, path: str) -> bool:
        """Open a file or folder with its default program."""
        if open_path(path):
            return True
        self.notice.emit("That file or folder no longer exists.")
        return False

    @Slot(str, result=bool)
    def revealFile(self, path: str) -> bool:
        """Show a file selected in File Explorer (its folder when selecting isn't possible)."""
        if select_in_explorer(path) or open_path(os.path.dirname(path)):
            return True
        self.notice.emit("That file or folder no longer exists.")
        return False

    @Slot(str)
    def openUrl(self, url: str) -> None:
        """Open a web page in the default browser (http and https only)."""
        if url.startswith(("https://", "http://")):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str)
    def copyText(self, text: str) -> None:
        """Put text on the clipboard."""
        QGuiApplication.clipboard().setText(text)

    @Slot(result=str)
    def clipboardText(self) -> str:
        """The clipboard's text (for Paste)."""
        return QGuiApplication.clipboard().text()

    @Slot(str, result=bool)
    def validLink(self, text: str) -> bool:
        """True when the text is a web link by its form ("youtu.be/..." typed bare counts); nothing is fetched."""
        try:
            check_url(as_link(text))
        except ValueError:
            return False
        return True

    @Slot(str, result=str)
    def localPath(self, url: str) -> str:
        """A file:// URL from a dialog or a drop as a local path ("" for anything else)."""
        qurl = QUrl(url)
        return qurl.toLocalFile() if qurl.isLocalFile() else ""

    @Slot(str, result=str)
    def readTextFile(self, url: str) -> str:
        """The text of a small local file chosen by the user (a link list or cookies file), at most 4 MB."""
        path = self.localPath(url) or url
        try:
            if os.path.getsize(path) > 4 * 1024 * 1024:
                self.notice.emit("That file is too large.")
                return ""
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                return handle.read()
        except OSError as error:
            write_log(f"Could not read {path}: {error}", "critical")
            self.notice.emit("That file couldn't be read.")
            return ""

    @Slot(str, str, result=bool)
    def writeTextFile(self, url: str, text: str) -> bool:
        """Save text to a file the user chose in a Save dialog."""
        path = self.localPath(url) or url
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as error:
            write_log(f"Could not write {path}: {error}", "critical")
            self.notice.emit("That file couldn't be saved.")
            return False
        self.notice.emit(f"Saved {os.path.basename(path)}.")
        return True

    def show_notices(self, *notices: str) -> None:
        """Show the start-up notices as one toast, adding one when the preferences file reset."""
        if take_read_error():
            notices = (*notices, _SETTINGS_RESET)
        text = " ".join(notice for notice in notices if notice)
        if text:
            self.notice.emit(text)

    def _set_theme(self, theme: str) -> None:
        if theme != self._theme:
            self._theme = theme
            self.themeChanged.emit(theme)
