"""Find yt-dlp, FFmpeg, ffprobe, and Deno: the app's managed copies, PATH, or custom locations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from gfgmd.core.platform import hidden_window_flags

TOOL_NAMES = ("yt-dlp", "ffmpeg", "ffprobe", "deno")
MANIFEST = "manifest.json"
_VERSION_ARGS = {"yt-dlp": ["--version"], "ffmpeg": ["-version"], "ffprobe": ["-version"], "deno": ["--version"]}


class ToolsMissing(RuntimeError):
    """One or more required programs could not be found."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"Missing required programs: {', '.join(missing)}")
        self.missing = missing


@dataclass(frozen=True)
class ToolSet:
    """Absolute paths to the four programs a download needs."""

    ytdlp: str
    ffmpeg: str
    ffprobe: str
    deno: str

    @property
    def ffmpeg_dir(self) -> str:
        """The folder holding ffmpeg (yt-dlp's --ffmpeg-location expects ffprobe beside it)."""
        return os.path.dirname(self.ffmpeg)

    def as_dict(self) -> dict[str, str]:
        """The paths by tool name."""
        return {"yt-dlp": self.ytdlp, "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe, "deno": self.deno}


def read_manifest(tools_root: Path) -> dict[str, Any]:
    """The managed tools' manifest: {tool: {"path": relative exe, "version": str, "sha256": str}}."""
    try:
        data = json.loads((tools_root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def managed_tools(tools_root: Path | None) -> dict[str, str]:
    """The managed copies that exist on disk, by tool name."""
    if tools_root is None:
        return {}
    found: dict[str, str] = {}
    for name, entry in read_manifest(tools_root).items():
        if name not in TOOL_NAMES or not isinstance(entry, dict):
            continue
        relative = entry.get("path")
        if not isinstance(relative, str):
            continue
        path = (tools_root / relative).resolve()
        if path.is_file() and _inside(path, tools_root):
            found[name] = str(path)
    return found


def path_tools() -> dict[str, str]:
    """The programs found on PATH, by tool name."""
    found: dict[str, str] = {}
    for name in TOOL_NAMES:
        location = shutil.which(name)
        if location:
            found[name] = os.path.abspath(location)
    return found


def resolve_tools(source: str = "managed", tools_root: Path | None = None,
                  custom: Mapping[str, str] | None = None) -> ToolSet:
    """Pick each program from the chosen source; managed copies fall back to PATH.

    Raises ToolsMissing naming every program that could not be found.
    """
    chosen: dict[str, str] = {}
    if source == "custom":
        for name in TOOL_NAMES:
            path = (custom or {}).get(name, "")
            if path and os.path.isfile(path):
                chosen[name] = os.path.abspath(path)
    elif source == "managed":
        chosen.update(managed_tools(tools_root))
    on_path = path_tools()
    for name in TOOL_NAMES:
        if name not in chosen and name in on_path:
            chosen[name] = on_path[name]
    missing = [name for name in TOOL_NAMES if name not in chosen]
    if missing:
        raise ToolsMissing(missing)
    return ToolSet(chosen["yt-dlp"], chosen["ffmpeg"], chosen["ffprobe"], chosen["deno"])


def tool_version(name: str, path: str, timeout: float = 30) -> str:
    """The version a program reports, or "" when it doesn't run."""
    try:
        result = subprocess.run([path, *_VERSION_ARGS[name]], capture_output=True, text=True, check=False,
                                timeout=timeout, creationflags=hidden_window_flags(),
                                encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    first = (result.stdout.strip().splitlines() or [""])[0]
    if name in ("ffmpeg", "ffprobe"):
        # "ffmpeg version n7.1-20-g... Copyright ..." -> "n7.1-20-g..."
        parts = first.split()
        return parts[2] if len(parts) > 2 and parts[1] == "version" else first
    if name == "deno":
        # "deno 2.9.8 (stable, release, x86_64-pc-windows-msvc)" -> "2.9.8"
        parts = first.split()
        return parts[1] if len(parts) > 1 else first
    return first


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.normcase(str(path)).startswith(os.path.normcase(str(root.resolve())) + os.sep)
    except OSError:
        return False
