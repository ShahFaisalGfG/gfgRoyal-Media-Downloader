# context.py - the services every controller shares: the library database, the sign-in vault,
# and where tools, caches, and downloads live. Built once at startup and passed to controllers.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from gfgmd.core.auth import SignInVault
from gfgmd.core.command import Auth
from gfgmd.core.sites import Site, resolve_site, site_by_key
from gfgmd.core.store import Store
from gfgmd.core.tools import ToolSet, resolve_tools
from gfgmd.utils.paths import cache_dir, default_audio_root, default_download_root, local_dir, local_subdir, tools_dir
from gfgmd.utils.settings import load_settings

# Sign-in methods whose cookies live in the vault (the others read a browser on each run).
VAULT_METHODS = ("file", "browser", "extension")


class AppContext:
    """Shared services; cheap to query from any thread."""

    def __init__(self, local: Path | None = None) -> None:
        base = local or Path(local_dir())
        self.store = Store(base / "library.db")
        self.vault = SignInVault(local_subdir("signins") if local is None else base / "signins")
        self.tools_root = tools_dir() if local is None else base / "tools"
        self.cache_dir = cache_dir() if local is None else base / "cache"
        self.run_root = local_subdir("run") if local is None else base / "run"
        self.jobs_root = local_subdir("jobs") if local is None else base / "jobs"
        self.signin_profiles = local_subdir("browser-profiles") if local is None else base / "browser-profiles"
        self.thumbnails_dir = local_subdir("thumbnails") if local is None else base / "thumbnails"

    def close(self) -> None:
        """Close the database."""
        self.store.close()

    @staticmethod
    def settings() -> dict[str, Any]:
        """The current preferences."""
        return load_settings()

    def download_root(self, kind: str = "video") -> Path:
        """Where downloads of this kind go: the preference, else Videos (or Music for audio)."""
        prefs = self.settings().get("downloads", {})
        if kind == "audio":
            folder = str(prefs.get("audio_folder", "") or "")
            return Path(folder) if folder else default_audio_root()
        folder = str(prefs.get("folder", "") or "")
        return Path(folder) if folder else default_download_root()

    def tools(self) -> ToolSet:
        """The programs to run, from the chosen source; raises ToolsMissing."""
        prefs = self.settings().get("tools", {})
        custom = {"yt-dlp": prefs.get("ytdlp_path", ""), "ffmpeg": prefs.get("ffmpeg_path", ""),
                  "ffprobe": _beside(prefs.get("ffmpeg_path", ""), "ffprobe"), "deno": prefs.get("deno_path", "")}
        return resolve_tools(str(prefs.get("source", "managed")), self.tools_root, custom)

    def job_dir(self, job_id: int) -> Path:
        """A job's scratch folder (its yt-dlp journal and link list)."""
        return self.jobs_root / str(job_id)

    def account_for(self, site_key: str, account_id: int | None = None) -> dict[str, Any] | None:
        """The sign-in record a job uses: the one it names, else the one for its site."""
        if account_id:
            account = self.store.account(account_id)
            if account is not None:
                return account
        return self.store.account_for_site(site_key)

    @staticmethod
    def site(site_key: str) -> Site:
        """The profile for a site key (generic for unknown sites)."""
        return site_by_key(site_key) or resolve_site(site_key)

    def browser_auth(self, account: dict[str, Any] | None) -> Auth | None:
        """--cookies-from-browser for accounts that read a browser on each run."""
        if account and account.get("method") == "firefox" and account.get("browser"):
            return Auth(browser=str(account["browser"]))
        return None


def _beside(path: str, program: str) -> str:
    """ffprobe sits beside a chosen ffmpeg."""
    if not path:
        return ""
    return os.path.join(os.path.dirname(path), program + os.path.splitext(path)[1])
