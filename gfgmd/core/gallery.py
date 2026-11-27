"""Save pictures with gallery-dl: a picture site's posts and profiles (pixiv, DeviantArt, Imgur, ...),
and the pictures in posts on sites whose videos yt-dlp saves (Instagram, X, Reddit, ...), where only
the pictures are taken so nothing is saved twice.

gallery-dl runs with its own configuration files ignored and every choice on the command line. It
prints a marked line for each picture it saves or skips, which is how the app learns of them; its
archive (an SQLite file per site) remembers what was saved, so a picture isn't saved twice. For
Download options, its JSON listing names a link's first pictures without saving any.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from gfgmd.core.analyze import Analysis, AnalyzeError, Entry
from gfgmd.core.command import Auth, folder_name, run_marker
from gfgmd.core.errors import CATEGORIES, Failure, classify
from gfgmd.core.jobs import JobResult
from gfgmd.core.naming import IMAGE_EXTENSIONS, unique_target
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import Snapshot
from gfgmd.core.runner import Runner, run_to_completion
from gfgmd.core.sites import site_by_key
from gfgmd.core.sources import Source, is_image_link
from gfgmd.core.tools import ToolSet

# A post's photos pass keeps only picture files.
_IMAGES_ONLY = f"extension.lower() in {tuple(sorted(IMAGE_EXTENSIONS))!r}"
# gallery-dl's name for a site where it differs from the app's.
_CATEGORY = {"x": "twitter"}
# gallery-dl's exit status is a set of these bits (OR-ed over every link it read).
_EXIT_AUTH, _EXIT_UNSUPPORTED = 16, 64
# Download options lists this many of a link's pictures at most: a profile can hold thousands.
LIST_LIMIT = 48
# gallery-dl's JSON listing marks each file with this message type: [3, url, details].
_URL_MESSAGE = 3


def photos_only(source: Source, url: str) -> bool:
    """True for a link gallery-dl saves on its own: a picture site's, or a direct link to a picture."""
    site = site_by_key(source.site)
    return (site is not None and site.gallery_only) or is_image_link(url)


def has_photos_pass(source: Source, options: DownloadOptions) -> bool:
    """True when a video download of this post also saves its pictures (gallery-dl, after yt-dlp)."""
    site = site_by_key(source.site)
    return (options.kind == "video" and options.save_photos and source.kind == "post"
            and site is not None and site.photos)


def _no_video(videos: JobResult) -> bool:
    return videos.failure is not None and videos.failure.category.key == "no_video"


def pictures_follow(videos: JobResult) -> bool:
    """True when a post's pictures pass runs after this video result: the videos were saved (or
    saved before), or the post has no video. A download that failed otherwise is reported as it is."""
    return videos.state == "done" or _no_video(videos)


def merge_results(videos: JobResult, pictures: JobResult) -> JobResult:
    """One result for a post's video download and its pictures pass: "1 video and 4 pictures saved".

    A post with pictures only (yt-dlp found no video) is done when its pictures were saved; pictures
    that couldn't be saved (a sign-in, say) leave the saved videos as they are and say why.
    """
    no_video = _no_video(videos)
    if not pictures_follow(videos):
        return videos
    if no_video or (not videos.files and not videos.archived):
        if pictures.files or pictures.archived or pictures.state != "done":
            return pictures
        return videos
    merged = JobResult(videos.state, videos.attempts, videos.files + pictures.files, videos.skipped, None,
                       videos.rename_errors, videos.archived + pictures.archived, videos.archived_ids, videos.kind,
                       pictures=len(pictures.files))
    if pictures.failure is not None and pictures.state != "done":
        merged.note = f"the pictures couldn't be saved: {pictures.failure.category.final}"
    return merged


@dataclass(frozen=True)
class GallerySpec:
    """One gallery-dl run: the link, where its pictures go, and how it signs in."""

    url: str
    source: Source
    root: Path  # the pictures folder (Preferences > Downloads)
    job_dir: Path  # the job's scratch folder: gallery-dl's own cache stays in it
    auth: Auth | None = None
    options: DownloadOptions = field(default_factory=lambda: DownloadOptions(kind="photo"))
    # Only pictures (the photos pass after yt-dlp saved a post's videos), or everything the link holds.
    images_only: bool = False
    title: str = ""

    @property
    def folder(self) -> Path:
        """The post's or profile's own folder; a post with one picture is moved out of it at the end."""
        return self.root / post_folder(self.source, self.url)

    @property
    def archive(self) -> Path:
        return self.root / ".archives" / f"{self.source.site}-photos.sqlite3"


def post_folder(source: Source, url: str) -> str:
    """A folder name for a post or profile: the site's name and the link's last part ("Instagram DLtSAJ3t3Ia")."""
    site = site_by_key(source.site)
    label = site.label if site is not None else source.site
    tail = next((part for part in reversed(url.split("?")[0].split("#")[0].rstrip("/").split("/")) if part), "")
    return folder_name(f"{label} {tail}".strip())


def _reading_args(spec: GallerySpec) -> list[str]:
    """What saving and listing share: no configuration files or prompts, the run's own cache, the
    pictures-only filter, the sign-in, and the proxy."""
    command = ["--config-ignore", "--no-input", "-o", f"cache.file={spec.job_dir / 'gallery-dl-cache.sqlite3'}"]
    if spec.images_only:
        category = _CATEGORY.get(spec.source.site, spec.source.site)
        command += ["--filter", _IMAGES_ONLY, "-o", f"extractor.{category}.videos=false"]
    if spec.auth is not None and spec.auth.cookies_file:
        command += ["-C", spec.auth.cookies_file]
    elif spec.auth is not None and spec.auth.browser:
        command += ["--cookies-from-browser", spec.auth.browser]
    if spec.options.proxy:
        command += ["--proxy", spec.options.proxy]
    return command


def gallery_command(spec: GallerySpec, tools: ToolSet, marker: str) -> list[str]:
    """The gallery-dl command for one link: the app's folder, archive, and speed limit, and a marked
    line for each picture saved or skipped."""
    command = [tools.gallery_dl, *_reading_args(spec), "-D", str(spec.folder)]
    if not spec.options.ignore_archive:  # Download again saves them whether or not they were saved before
        command += ["--download-archive", str(spec.archive)]
    command += ["-o", "output.shorten=false",
               "--Print", f"after:{marker}saved {{_path}}",
               "--Print", f"skip:{marker}skipped {{_path}}",
               # A direct link's picture keeps its own file name (gallery-dl names it after the whole address).
               "-o", "extractor.directlink.filename={filename}.{extension}"]
    if spec.options.limit_rate > 0:
        command += ["-r", str(spec.options.limit_rate)]
    return command + ["--", spec.url]


def list_command(spec: GallerySpec, tools: ToolSet) -> list[str]:
    """gallery-dl's JSON listing of a link's first pictures (nothing is saved), for Download options."""
    return [tools.gallery_dl, *_reading_args(spec), "-J", "--range", f"1-{LIST_LIMIT}", "--", spec.url]


def parse_listing(text: str) -> list[Entry]:
    """The files in gallery-dl's JSON listing, numbered from 1; a picture's own address is its preview."""
    try:
        messages = json.loads(text) if text.strip() else []
    except ValueError:
        return []
    entries: list[Entry] = []
    for message in messages if isinstance(messages, list) else []:
        if not (isinstance(message, list) and len(message) >= 3 and message[0] == _URL_MESSAGE
                and isinstance(message[2], dict)):
            continue
        url, info = str(message[1]), message[2]
        extension = str(info.get("extension") or "").lower()
        number = len(entries) + 1
        name = ".".join(part for part in (str(info.get("filename") or ""), extension) if part)
        preview = url if extension in IMAGE_EXTENSIONS and url.startswith("https://") else ""
        entries.append(Entry(str(number), name or f"Picture {number}", number, url=url, thumbnail=preview))
    return entries


def list_pictures(spec: GallerySpec, tools: ToolSet, runner: Runner = run_to_completion,
                  stop: threading.Event | None = None) -> Analysis:
    """Read a link's first pictures (at most LIST_LIMIT) for Download options, saving nothing.

    Raises AnalyzeError with the reason (a sign-in, an unsupported link, gallery-dl missing).
    """
    if not tools.gallery_dl:
        raise AnalyzeError(Failure(CATEGORIES["gallery_missing"], ""))
    spec.job_dir.mkdir(parents=True, exist_ok=True)
    out: list[str] = []
    errors: list[str] = []

    def feed(stream: str, line: str) -> None:
        if stream == "out":
            out.append(line)
        elif "][error]" in line:
            errors.append(line.split("][error]", 1)[1].strip())

    code, killed = runner(list_command(spec, tools), feed, stop or threading.Event())
    entries = parse_listing("\n".join(out))
    if killed:
        raise AnalyzeError(Failure(CATEGORIES["unknown"], "stopped"))
    if not entries and code != 0:
        raise AnalyzeError(gallery_failure(code, errors, spec.auth is not None))
    # A direct link is titled by its picture's name; a post or album by its site and its own name.
    named = entries[0].title if entries and is_image_link(spec.url) else ""
    return Analysis("photo", spec.title or named or post_folder(spec.source, spec.url), "gallery-dl", spec.url,
                    thumbnail=next((entry.thumbnail for entry in entries if entry.thumbnail), ""),
                    entries=entries, selectable=False)


def gallery_failure(code: int, errors: list[str], signed_in: bool) -> Failure:
    """What went wrong, from gallery-dl's error lines and its exit status bits."""
    if code & _EXIT_AUTH:
        return Failure(CATEGORIES["auth_required"], errors[-1] if errors else "")
    if code & _EXIT_UNSUPPORTED:
        return Failure(CATEGORIES["unsupported"], errors[-1] if errors else "")
    return classify(errors[-1] if errors else f"gallery-dl exited with status {code}", signed_in=signed_in)


class GalleryExecutor:
    """Save one link's pictures; call run() on a worker thread and stop() from any thread.

    It offers the queue what JobExecutor does (run, stop, snapshot, partial_files), so the queue runs
    it as one of its jobs, alone or after a post's video download.
    """

    def __init__(self, spec: GallerySpec, tools: Callable[[], ToolSet],
                 on_file: Callable[[dict[str, Any], Path], None] | None = None,
                 runner: Runner = run_to_completion) -> None:
        self._spec = spec
        self._tools = tools
        self._on_file = on_file
        self._runner = runner
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._marker = run_marker()
        self._saved: list[Path] = []
        self._skipped = 0
        self._errors: list[str] = []
        self._snap = Snapshot(title=spec.title, stage="Saving pictures")

    def run(self) -> JobResult:
        tools = self._tools()
        if not tools.gallery_dl:
            return JobResult("failed", attempts=0, kind="photo", failure=Failure(CATEGORIES["gallery_missing"], ""))
        spec = self._spec
        spec.folder.mkdir(parents=True, exist_ok=True)
        spec.archive.parent.mkdir(parents=True, exist_ok=True)
        spec.job_dir.mkdir(parents=True, exist_ok=True)
        code, killed = self._runner(gallery_command(spec, tools, self._marker), self._feed, self._stop)
        with self._lock:
            saved, skipped, errors = list(self._saved), self._skipped, list(self._errors)
        files = self._flatten(saved)
        if killed or self._stop.is_set():
            return JobResult("stopped", attempts=1, files=files, kind="photo")
        result = JobResult("done", attempts=1, files=files, archived=skipped, kind="photo")
        if code != 0 and not files:
            failure = gallery_failure(code, errors, self._spec.auth is not None)
            result.failure = failure
            result.state = "needs_auth" if failure.category.action == "signin" else "failed"
        return result

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> Snapshot:
        with self._lock:
            return replace(self._snap, items_done=len(self._saved))

    def partial_files(self) -> set[str]:
        """gallery-dl's unfinished ".part" files in the post's folder (for removing a cancelled download)."""
        folder = self._spec.folder
        return {str(path) for path in folder.glob("*.part")} if folder.is_dir() else set()

    def _feed(self, stream: str, line: str) -> None:
        text = line.strip()
        if text.startswith(self._marker):
            kind, _, path = text[len(self._marker):].partition(" ")
            if kind == "saved" and path:
                self._found(Path(path))
            elif kind == "skipped":
                with self._lock:
                    self._skipped += 1
        elif stream == "err" and "][error]" in text:
            with self._lock:
                self._errors.append(text.split("][error]", 1)[1].strip())

    def _found(self, path: Path) -> None:
        if not path.is_file():
            return
        with self._lock:
            self._saved.append(path)
            self._snap.stage = f"Saving pictures ({len(self._saved)} saved)"

    def _flatten(self, saved: list[Path]) -> list[Path]:
        """A post with one picture needs no folder of its own: the picture goes straight into the
        pictures folder (under a free name), and the emptied folder goes. Then each is reported."""
        folder = self._spec.folder
        files = saved
        if len(saved) == 1 and saved[0].parent == folder and not any(
                entry for entry in folder.iterdir() if entry != saved[0]):
            single = saved[0]
            occupied = {entry.name.casefold() for entry in self._spec.root.iterdir()}
            target = unique_target(self._spec.root, single.stem, "", single.suffix[1:], occupied)
            try:
                os.replace(single, target)
                shutil.rmtree(folder, ignore_errors=True)
                files = [target]
            except OSError:
                files = saved  # held open: it stays in the post's folder
        elif not saved and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()  # nothing came of it (all saved before, or none at all)
        for path in files:
            if self._on_file is not None:
                # "_root": the pictures folder, which the Library groups them under (a post's video
                # download has the videos folder as its own).
                self._on_file({"id": path.stem, "title": path.stem, "filepath": str(path),
                               "webpage_url": self._spec.url, "extractor_key": self._spec.source.site,
                               "_root": str(self._spec.root)}, path)
        return files

