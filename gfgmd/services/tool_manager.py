# tool_manager.py - install, update, and report the app's copies of the download tools: yt-dlp,
# FFmpeg, and Deno, which every download needs, and gallery-dl and spotDL, which pictures and long
# Spotify playlists need
#
# Blocking methods for worker threads; ToolsController runs them off the GUI thread, and the queue
# calls update_ytdlp() from a download's own thread when yt-dlp looks out of date. One lock keeps
# two downloads from installing the same update at once.

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from gfgmd.config.defaults import UpdateDefaults
from gfgmd.core.tool_install import (
    Package,
    ToolInstallCancelled,
    ToolInstallError,
    install,
    packages,
    remove_unused,
    rollback,
    update_available,
)
from gfgmd.core.tools import (EXTRA_TOOLS, TOOL_NAMES, ToolsMissing, managed_tools, path_tools, read_manifest,
                              tool_version)
from gfgmd.services.context import AppContext
from gfgmd.services.update_install import is_metered
from gfgmd.utils.logging import write_log

# After a failure that suggests yt-dlp is out of date, look for an update at most this often.
UPDATE_RECHECK_S = 3600

Progress = Callable[[str, int, int], None]


class ToolManager:
    """The managed tools' state and changes."""

    def __init__(self, context: AppContext, metered: Callable[[], bool] = is_metered) -> None:
        self._context = context
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._metered = metered

    def hold_updates(self) -> bool:
        """True when automatic tool updates should wait: a metered or roaming connection, unless
        Preferences > Updates and logs allows updates over one."""
        if self._context.settings().get("updates", {}).get("allow_metered", UpdateDefaults.ALLOW_METERED):
            return False
        return self._metered()

    @property
    def tools_root(self):
        """The managed tools' folder."""
        return self._context.tools_root

    def _prefs(self) -> dict[str, Any]:
        return self._context.settings().get("tools", {})

    def missing(self) -> list[str]:
        """Required programs that can't be found with the current settings."""
        try:
            self._context.tools()
            return []
        except ToolsMissing as error:
            return error.missing

    def missing_extras(self) -> list[str]:
        """Extra programs (gallery-dl, spotDL) that can't be found with the current settings."""
        found = self._context.tool_paths()
        return [name for name in EXTRA_TOOLS if name not in found]

    def status(self) -> list[dict[str, Any]]:
        """Each program's location, where it comes from, and its version.

        A managed copy's version is the one it reported when it was installed (in the manifest), so a
        finished install shows its new versions at once. Other programs run once each, side by side,
        so the slowest one sets the wait.
        """
        managed = managed_tools(self._context.tools_root)
        on_path = path_tools()
        manifest = read_manifest(self._context.tools_root)
        chosen = self._context.tool_paths()
        entries = {name: entry if isinstance(entry := manifest.get(name), dict) else {} for name in TOOL_NAMES}

        def version(name: str) -> str:
            path = chosen.get(name, "")
            recorded = entries[name].get("version")
            if path and path == managed.get(name) and isinstance(recorded, str) and recorded:
                return recorded
            return tool_version(name, path) if path else ""

        with ThreadPoolExecutor(max_workers=len(TOOL_NAMES)) as pool:
            versions = dict(zip(TOOL_NAMES, pool.map(version, TOOL_NAMES)))
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
            rows.append({
                "name": name,
                "path": path,
                "origin": origin,
                "version": versions[name],
                "canRollBack": isinstance(entries[name].get("previous"), dict),
            })
        return rows

    def packages_for(self, names: list[str]) -> list[Package]:
        """The packages that provide these programs (ffprobe comes with FFmpeg)."""
        wanted = {"ffmpeg" if name == "ffprobe" else name for name in names}
        return [package for package in packages(str(self._prefs().get("channel", "stable"))) if package.tool in wanted]

    def install(self, names: list[str], progress: Progress, cancel: threading.Event) -> list[str]:
        """Install the packages for these programs; returns the tools installed.

        An extra program (gallery-dl, spotDL) that fails is logged and left out of the result, so the
        programs every download needs still install. Raises ToolInstallError for a required program,
        or OSError when the drive refuses one of its files.
        """
        installed: list[str] = []
        with self._lock:
            chosen = self.packages_for(names)
            for index, package in enumerate(chosen, start=1):
                prefix = f"{package.label} ({index} of {len(chosen)})" if len(chosen) > 1 else package.label
                try:
                    install(package, self._context.tools_root,
                            lambda stage, done, total, p=prefix: progress(f"{p}: {stage}", done, total),
                            cancel, channel=str(self._prefs().get("channel", "stable")))
                except ToolInstallCancelled:
                    raise
                except (ToolInstallError, OSError) as error:
                    if package.tool not in EXTRA_TOOLS:
                        raise
                    write_log(f"Installing {package.label} failed: {error}", "critical")
                    continue
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
        at most once an hour unless forced. On a metered connection it updates only when forced or
        allowed (see hold_updates): the download then fails with its Update tools button, which still
        works there.
        """
        if str(self._prefs().get("source", "managed")) != "managed":
            return False
        if "yt-dlp" not in managed_tools(self._context.tools_root):
            return False
        if not force and self.hold_updates():
            write_log("yt-dlp wasn't updated after a download failure: the connection is metered", "general")
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
