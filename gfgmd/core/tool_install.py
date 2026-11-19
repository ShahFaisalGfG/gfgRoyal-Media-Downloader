"""Download, verify, and install the managed copies of yt-dlp, FFmpeg, and Deno.

Each package comes from its official GitHub releases and must match the SHA-256 its project
publishes next to it. Downloads use HTTPS only and may be redirected only to GitHub's own hosts;
they resume after an interruption and stop at a size limit. A package is unpacked into a staging
folder, checked for paths that would escape it, smoke-tested, and only then made current by
rewriting the manifest atomically. The previous version stays on disk for one rollback.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from gfgmd.core.tools import MANIFEST, read_manifest, tool_version

ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                 "github-releases.githubusercontent.com", "codeload.github.com")
MAX_PACKAGE_BYTES = 400 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
MAX_CHECKSUM_BYTES = 256 * 1024
TIMEOUT_S = 30
_CHUNK = 256 * 1024
_HEX64 = re.compile(r"\b([0-9a-fA-F]{64})\b")
_TAG = re.compile(r"/releases/download/([^/]+)/")
USER_AGENT = "gfgRoyal-Media-Downloader (+https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader)"

Progress = Callable[[str, int, int], None]  # (stage text, bytes done, bytes total)


class ToolInstallError(Exception):
    """A package could not be fetched, verified, or installed; the message suits the UI."""


@dataclass(frozen=True)
class Package:
    """One downloadable package and the programs it provides."""

    tool: str  # yt-dlp, ffmpeg, deno
    label: str
    base_url: str  # .../releases/latest/download/
    # The release's checksum list, from which the asset is picked by the `assets` patterns (best first);
    # when "", the single asset `asset_name` has its own "<asset>.sha256sum" file.
    checksums: str
    assets: tuple[str, ...]
    programs: dict[str, str]  # program name -> file name inside the package
    approx_mb: int
    asset_name: str = ""


def _arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"


def packages(channel: str = "stable") -> list[Package]:
    """The packages for this PC: yt-dlp (stable or nightly), FFmpeg, and Deno."""
    arm = _arch() == "arm64"
    ytdlp_repo = "yt-dlp/yt-dlp-nightly-builds" if channel == "nightly" else "yt-dlp/yt-dlp"
    return [
        Package("yt-dlp", "yt-dlp", f"https://github.com/{ytdlp_repo}/releases/latest/download/", "SHA2-256SUMS",
                (r"yt-dlp_win_arm64\.zip",) if arm else (r"yt-dlp_win\.zip",),
                {"yt-dlp": "yt-dlp.exe"}, 35),
        # yt-dlp's patched static builds (yt-dlp recommends them); the "-shared" variants need DLLs.
        Package("ffmpeg", "FFmpeg", "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/",
                "checksums.sha256",
                (r"ffmpeg-master-latest-winarm64-gpl\.zip",) if arm else (r"ffmpeg-master-latest-win64-gpl\.zip",),
                {"ffmpeg": "ffmpeg.exe", "ffprobe": "ffprobe.exe"}, 200),
        Package("deno", "Deno", "https://github.com/denoland/deno/releases/latest/download/", "", (),
                {"deno": "deno.exe"}, 45,
                asset_name="deno-aarch64-pc-windows-msvc.zip" if arm else "deno-x86_64-pc-windows-msvc.zip"),
    ]


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    """Follows redirects only to GitHub's hosts, remembering each one (the release tag is in the first)."""

    def __init__(self) -> None:
        super().__init__()
        self.chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib's hook
        check_url(newurl)
        self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str) -> None:
    """Allow only HTTPS URLs on GitHub's hosts."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise ToolInstallError(f"Refused to download from {host or url}: only GitHub over HTTPS is allowed")


def open_url(url: str, headers: dict[str, str] | None = None) -> Any:
    """Open a GitHub URL, following redirects only to GitHub's hosts."""
    check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    redirects = _GitHubOnly()
    response = urllib.request.build_opener(redirects).open(request, timeout=TIMEOUT_S)
    response.redirect_chain = redirects.chain
    return response


Opener = Callable[[str, dict[str, str] | None], Any]


def read_text(url: str, opener: Opener = open_url, limit: int = MAX_CHECKSUM_BYTES) -> tuple[str, str]:
    """A small text file, and the redirect that named its release (GitHub's latest-download link
    redirects to /releases/download/<tag>/ before its download servers)."""
    try:
        with opener(url, None) as response:
            data = response.read(limit + 1)
            chain = [*getattr(response, "redirect_chain", []), response.geturl()]
            final = next((link for link in chain if _TAG.search(link)), chain[-1])
    except urllib.error.HTTPError as error:
        raise ToolInstallError(f"{url} answered HTTP {error.code}") from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ToolInstallError(f"Couldn't reach GitHub: {getattr(error, 'reason', error)}") from error
    if len(data) > limit:
        raise ToolInstallError(f"{url} is unexpectedly large")
    return data.decode("utf-8", errors="replace"), final


def parse_checksums(text: str) -> dict[str, str]:
    """`<sha256>  <name>` lines (sha256sum format, optional "*" binary marker) as {name: hash}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and _HEX64.fullmatch(parts[0]):
            sums[parts[-1].lstrip("*")] = parts[0].lower()
    return sums


def release_tag(final_url: str) -> str:
    """The release tag in a resolved download URL, or ""."""
    match = _TAG.search(final_url)
    return match.group(1) if match else ""


@dataclass(frozen=True)
class Resolved:
    """A package's chosen asset, its expected hash, and the release it belongs to."""

    package: Package
    asset: str
    sha256: str
    tag: str


def resolve(package: Package, opener: Opener = open_url) -> Resolved:
    """Find the asset to download and the hash it must have."""
    if package.checksums:
        text, final = read_text(package.base_url + package.checksums, opener)
        sums = parse_checksums(text)
        asset = _pick(package, sums)
        return Resolved(package, asset, sums[asset], release_tag(final))
    asset = package.asset_name
    text, final = read_text(package.base_url + asset + ".sha256sum", opener)
    match = _HEX64.search(text)
    if match is None:
        raise ToolInstallError(f"{package.label}'s checksum file has no SHA-256")
    return Resolved(package, asset, match.group(1).lower(), release_tag(final))


def _pick(package: Package, sums: dict[str, str]) -> str:
    """The first asset in the checksum list that matches the package's patterns, best pattern first."""
    for pattern in package.assets:
        regex = re.compile(pattern)
        for name in sorted(sums):
            if regex.fullmatch(name):
                return name
    raise ToolInstallError(f"{package.label}'s release has no Windows build this app recognizes")


def download(url: str, target: Path, sha256: str, progress: Progress | None = None,
             cancel: threading.Event | None = None, opener: Opener = open_url,
             limit: int = MAX_PACKAGE_BYTES) -> Path:
    """Download to target, resuming a ".part" file, and verify the SHA-256; returns target."""
    part = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    start = part.stat().st_size if part.exists() else 0
    digest = hashlib.sha256()
    if start:
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
    headers = {"Range": f"bytes={start}-"} if start else None
    try:
        with opener(url, headers) as response:
            status = getattr(response, "status", 200)
            if start and status != 206:  # the server ignored the range: start over
                start, digest = 0, hashlib.sha256()
            length = response.headers.get("Content-Length")
            total = start + int(length) if length and length.isdigit() else 0
            if total > limit:
                raise ToolInstallError("The package is larger than expected")
            done = start
            with part.open("ab" if start else "wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise ToolInstallError("Download cancelled")
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > limit:
                        raise ToolInstallError("The package is larger than expected")
                    handle.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress("Downloading", done, total)
    except urllib.error.HTTPError as error:
        if error.code == 416:  # the part file is complete or longer than the asset: start over
            part.unlink(missing_ok=True)
        raise ToolInstallError(f"The download failed: HTTP {error.code}") from error
    except (urllib.error.URLError, OSError) as error:
        raise ToolInstallError(f"The download failed: {getattr(error, 'reason', error)}") from error
    if digest.hexdigest() != sha256.lower():
        part.unlink(missing_ok=True)
        raise ToolInstallError("The download doesn't match its published checksum, so it was deleted")
    os.replace(part, target)
    return target


def safe_extract(archive: Path, folder: Path, wanted: set[str] | None = None) -> list[Path]:
    """Unpack a zip into folder, refusing paths that would escape it; returns the files written.

    With `wanted`, only members whose file names are in it are written (FFmpeg's zip carries more).
    """
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    written: list[Path] = []
    total = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                name = member.filename.replace("\\", "/")
                pure = PurePosixPath(name)
                if member.is_dir():
                    continue
                if pure.is_absolute() or ".." in pure.parts or ":" in name or not pure.parts:
                    raise ToolInstallError(f"The package contains an unsafe path: {name}")
                if wanted is not None and pure.name not in wanted:
                    continue
                total += member.file_size
                if total > MAX_UNPACKED_BYTES:
                    raise ToolInstallError("The package unpacks to more than expected")
                relative = Path(pure.name) if wanted is not None else Path(*pure.parts)
                destination = (root / relative).resolve()
                if not str(destination).startswith(str(root) + os.sep):
                    raise ToolInstallError(f"The package contains an unsafe path: {name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink, _CHUNK)
                written.append(destination)
    except zipfile.BadZipFile as error:
        raise ToolInstallError("The package is damaged") from error
    return written


def install(package: Package, tools_root: Path, progress: Progress | None = None,
            cancel: threading.Event | None = None, opener: Opener = open_url,
            channel: str = "stable") -> dict[str, Any]:
    """Download, verify, unpack, smoke-test, and switch one package; returns its manifest entries."""
    progress = progress or (lambda stage, done, total: None)
    progress("Checking the latest release", 0, 0)
    resolved = resolve(package, opener)
    downloads = tools_root / ".downloads"
    archive = download(package.base_url + resolved.asset, downloads / resolved.asset, resolved.sha256, progress,
                       cancel, opener)
    progress("Unpacking", 0, 0)
    version = resolved.tag or resolved.sha256[:12]
    folder_name = f"{_slug(version)}-{resolved.sha256[:8]}"
    staging = tools_root / ".staging" / f"{package.tool}-{folder_name}"
    shutil.rmtree(staging, ignore_errors=True)
    wanted = set(package.programs.values()) if package.tool == "ffmpeg" else None
    safe_extract(archive, staging, wanted)
    programs: dict[str, Path] = {}
    for name, file_name in package.programs.items():
        found = sorted(staging.rglob(file_name), key=lambda path: len(path.parts))
        if not found:
            shutil.rmtree(staging, ignore_errors=True)
            raise ToolInstallError(f"{package.label}'s package has no {file_name}")
        programs[name] = found[0]
    progress("Testing", 0, 0)
    for name, path in programs.items():
        if not tool_version(name, str(path)):
            shutil.rmtree(staging, ignore_errors=True)
            raise ToolInstallError(f"{path.name} from {package.label} didn't run on this PC")
    final = tools_root / package.tool / folder_name
    shutil.rmtree(final, ignore_errors=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    entries = {}
    for name, path in programs.items():
        relative = (final / path.relative_to(staging)).relative_to(tools_root).as_posix()
        entries[name] = {"path": relative, "version": tool_version(name, str(tools_root / relative)) or version,
                         "sha256": resolved.sha256, "asset": resolved.asset, "tag": resolved.tag,
                         "channel": channel if package.tool == "yt-dlp" else ""}
    update_manifest(tools_root, entries)
    archive.unlink(missing_ok=True)
    progress("Installed", 1, 1)
    return entries


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)[:40] or "release"


def update_manifest(tools_root: Path, entries: dict[str, Any]) -> None:
    """Make entries current, remembering each tool's previous entry for one rollback."""
    manifest = read_manifest(tools_root)
    for name, entry in entries.items():
        old = manifest.get(name)
        if isinstance(old, dict) and old.get("path") != entry.get("path"):
            entry = {**entry, "previous": {key: value for key, value in old.items() if key != "previous"}}
        manifest[name] = entry
    write_manifest(tools_root, manifest)


def write_manifest(tools_root: Path, manifest: dict[str, Any]) -> None:
    """Replace manifest.json in one step."""
    tools_root.mkdir(parents=True, exist_ok=True)
    temp = tools_root / (MANIFEST + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, tools_root / MANIFEST)


def rollback(tools_root: Path, tool_names: tuple[str, ...]) -> bool:
    """Go back to each program's previous version; True when anything changed."""
    manifest = read_manifest(tools_root)
    changed = False
    for name in tool_names:
        entry = manifest.get(name)
        previous = entry.get("previous") if isinstance(entry, dict) else None
        if isinstance(previous, dict) and (tools_root / str(previous.get("path", ""))).is_file():
            manifest[name] = previous
            changed = True
    if changed:
        write_manifest(tools_root, manifest)
    return changed


def remove_unused(tools_root: Path) -> None:
    """Delete versions the manifest no longer points to (current or previous) and stale staging."""
    manifest = read_manifest(tools_root)
    keep: set[Path] = set()
    for entry in manifest.values():
        for item in (entry, entry.get("previous") if isinstance(entry, dict) else None):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                parts = Path(item["path"]).parts
                if len(parts) >= 2:
                    keep.add((tools_root / parts[0] / parts[1]).resolve())
    for tool in ("yt-dlp", "ffmpeg", "deno"):
        folder = tools_root / tool
        if not folder.is_dir():
            continue
        for version_dir in folder.iterdir():
            if version_dir.is_dir() and version_dir.resolve() not in keep:
                shutil.rmtree(version_dir, ignore_errors=True)
    shutil.rmtree(tools_root / ".staging", ignore_errors=True)


def latest_tag(package: Package, opener: Opener = open_url) -> tuple[str, str]:
    """The newest release's tag and asset hash, read from the small checksum file only."""
    resolved = resolve(package, opener)
    return resolved.tag, resolved.sha256


def update_available(package: Package, tools_root: Path, opener: Opener = open_url) -> bool:
    """True when the newest release's asset differs from the installed one."""
    _, sha256 = latest_tag(package, opener)
    entry = read_manifest(tools_root).get(next(iter(package.programs)))
    return not (isinstance(entry, dict) and entry.get("sha256") == sha256)
