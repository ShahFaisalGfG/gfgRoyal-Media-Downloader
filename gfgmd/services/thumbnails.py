# thumbnails.py - a disk cache of video thumbnails for the lists
#
# QML asks for a thumbnail with localFor(url, thumbnails.revision): a cached file comes back at
# once; otherwise "" comes back and a background fetch starts. Each finished fetch bumps
# `revision`, which re-evaluates those bindings so the image appears. Fetches use HTTPS only (through
# the app's proxy), stop at a size limit, and must decode as an image; the cache prunes itself to a
# size cap.

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QImage

from gfgmd.core import web
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.logging import write_log

MAX_IMAGE_BYTES = 3 * 1024 * 1024
CACHE_LIMIT = 200 * 1024 * 1024
CACHE_TARGET = 150 * 1024 * 1024
_TIMEOUT_S = 15
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) gfgRoyal-Media-Downloader"


def cache_file(folder: Path, url: str) -> Path:
    """Where the cache keeps a thumbnail's image (it may not be fetched yet)."""
    return folder / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")


def _fetch(url: str, target: Path) -> Path:
    """Download one image to target (written atomically); raises on any failure."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    # Through the app's proxy; a redirect away from HTTPS is refused before it is followed.
    with web.open_url(request, _TIMEOUT_S) as response:
        data = response.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("thumbnail too large")
    image = QImage()
    if not image.loadFromData(data):
        raise ValueError("not an image")
    temp = target.with_suffix(".tmp")
    temp.write_bytes(data)
    os.replace(temp, target)
    return target


def prune(folder: Path, limit: int = CACHE_LIMIT, target: int = CACHE_TARGET) -> int:
    """Delete the oldest cached images while the folder is over `limit`; returns files removed."""
    files = [entry for entry in folder.glob("*.img") if entry.is_file()]
    total = sum(entry.stat().st_size for entry in files)
    if total <= limit:
        return 0
    removed = 0
    for entry in sorted(files, key=lambda item: item.stat().st_mtime):
        if total <= target:
            break
        try:
            size = entry.stat().st_size
            entry.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


class ThumbnailCache(QObject):
    """Cached thumbnails for QML lists."""

    revisionChanged = Signal()

    def __init__(self, folder: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._folder = folder
        self._folder.mkdir(parents=True, exist_ok=True)
        self._runner = TaskRunner(4, self)
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._revision = 0
        self._runner.start(prune, self._folder)

    @Property(int, notify=revisionChanged)
    def revision(self) -> int:
        """Bumped whenever a thumbnail arrives."""
        return self._revision

    def _path(self, url: str) -> Path:
        return cache_file(self._folder, url)

    @Slot(str, int, result=str)
    def localFor(self, url: str, revision: int = 0) -> str:  # noqa: ARG002 - revision drives QML re-evaluation
        """The cached file's URL, or "" while it is being fetched (or when it can't be)."""
        if not url or urlsplit(url).scheme != "https":
            return ""
        path = self._path(url)
        if path.is_file():
            return QUrl.fromLocalFile(str(path)).toString()
        if url not in self._pending and url not in self._failed:
            self._pending.add(url)
            self._runner.start(_fetch, url, path, on_done=lambda _path, u=url: self._arrived(u),
                               on_error=lambda message, u=url: self._missed(u, message))
        return ""

    def _arrived(self, url: str) -> None:
        self._pending.discard(url)
        self._revision += 1
        self.revisionChanged.emit()

    def _missed(self, url: str, message: str) -> None:
        self._pending.discard(url)
        self._failed.add(url)
        write_log(f"Thumbnail not loaded ({message}): {url}", "general")

    def shutdown(self) -> None:
        """Stop pending fetches."""
        self._runner.shutdown(1000)
