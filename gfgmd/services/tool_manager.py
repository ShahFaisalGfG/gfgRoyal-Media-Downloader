# tool_manager.py - install, update, and report the app's copies of yt-dlp, FFmpeg, and Deno
#
# Blocking methods for worker threads; ToolsController runs them off the GUI thread, and the queue
# calls update_ytdlp() from a download's own thread when yt-dlp looks out of date. One lock keeps
# two downloads from installing the same update at once.

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from gfgmd.core.tool_install import (
    Package,
    ToolInstallError,
    install,
    packages,
    remove_unused,
    rollback,
    update_available,
)
from gfgmd.core.tools import TOOL_NAMES, ToolsMissing, managed_tools, path_tools, read_manifest, tool_version
from gfgmd.services.context import AppContext
from gfgmd.utils.logging import write_log

# After a failure that suggests yt-dlp is out of date, look for an update at most this often.
UPDATE_RECHECK_S = 3600

Progress = Callable[[str, int, int], None]


class ToolManager:
    """The managed tools' state and changes."""

    def __init__(self, context: AppContext) -> None:
        self._context = context
        self._lock = threading.Lock()
        self._last_check = 0.0

    @property
    def tools_root(self):
        """The managed tools' folder."""
        return self._context.tools_root

    def _prefs(self) -> dict[str, Any]:
        return self._context.settings().get("tools", {})

    def missing(self) -> list[str]:
        """Programs that can't be found with the current settings."""
        try:
            self._context.tools()
            return []
        except ToolsMissing as error:
            return error.missing

    def status(self) -> list[dict[str, Any]]:
        """Each program's location, where it comes from, and its version (runs each program once)."""
        managed = managed_tools(self._context.tools_root)
        on_path = path_tools()
        manifest = read_manifest(self._context.tools_root)
        try:
            chosen = self._context.tools().as_dict()
        except ToolsMissing:
            chosen = {}
        rows = []
        for name in TOOL_NAMES:
            path = chosen.get(name, "")
            if not path:
                origin = "missing"
            elif path == managed.get(name):
                origin = "managed"
            elif path == on_path.get(name):
                origin = "path"
            else:
                origin = "custom"
            entry = manifest.get(name) if isinstance(manifest.get(name), dict) else {}
            rows.append({
                "name": name,
                "path": path,
                "origin": origin,
                "version": tool_version(name, path) if path else "",
                "canRollBack": isinstance(entry, dict) and isinstance(entry.get("previous"), dict),
            })
        return rows

    def packages_for(self, names: list[str]) -> list[Package]:
        """The packages that provide these programs (ffprobe comes with FFmpeg)."""
        wanted = {"ffmpeg" if name == "ffprobe" else name for name in names}
        return [package for package in packages(str(self._prefs().get("channel", "stable"))) if package.tool in wanted]

    def install(self, names: list[str], progress: Progress, cancel: threading.Event) -> list[str]:
        """Install the packages for these programs; returns the tools installed.

        Raises ToolInstallError, or OSError when the drive refuses a file.
        """
        installed: list[str] = []
        with self._lock:
            chosen = self.packages_for(names)
            for index, package in enumerate(chosen, start=1):
                prefix = f"{package.label} ({index} of {len(chosen)})" if len(chosen) > 1 else package.label
                install(package, self._context.tools_root,
                        lambda stage, done, total, p=prefix: progress(f"{p}: {stage}", done, total),
                        cancel, channel=str(self._prefs().get("channel", "stable")))
                installed.append(package.tool)
            remove_unused(self._context.tools_root)
        return installed

    def check_updates(self) -> list[str]:
        """Managed programs with a newer release (reads only the small checksum files).

        Raises ToolInstallError when no program could be checked at all (usually no connection), so
        an offline check never reads as "up to date".
        """
        names = []
        checked = 0
        failure: ToolInstallError | None = None
        for package in packages(str(self._prefs().get("channel", "stable"))):
            if next(iter(package.programs)) not in managed_tools(self._context.tools_root):
                continue
            try:
                if update_available(package, self._context.tools_root):
                    names.append(package.tool)
                checked += 1
            except ToolInstallError as error:
                write_log(f"Update check for {package.label} failed: {error}", "general")
                failure = error
        if failure is not None and not checked:
            raise failure
        return names

    def update_ytdlp(self, force: bool = False) -> bool:
        """Install a newer yt-dlp when the managed copy is in use; True when it changed.

        Called from download threads after errors that a newer yt-dlp usually fixes, so it checks
        at most once an hour unless forced.
        """
        if str(self._prefs().get("source", "managed")) != "managed":
            return False
        if "yt-dlp" not in managed_tools(self._context.tools_root):
            return False
        with self._lock:
            now = time.monotonic()
            if not force and self._last_check and now - self._last_check < UPDATE_RECHECK_S:
                return False
            self._last_check = now
        try:
            package = self.packages_for(["yt-dlp"])[0]
            if not update_available(package, self._context.tools_root):
                return False
            self.install(["yt-dlp"], lambda stage, done, total: None, threading.Event())
            write_log("yt-dlp was updated after a download failure", "general")
            return True
        except (ToolInstallError, OSError) as error:
            write_log(f"yt-dlp update failed: {error}", "critical")
            return False

    def roll_back(self, tool: str) -> bool:
        """Return a program to its previous version."""
        names = ("ffmpeg", "ffprobe") if tool in ("ffmpeg", "ffprobe") else (tool,)
        with self._lock:
            return rollback(self._context.tools_root, names)
