"""Clean file names: turn yt-dlp's staged names into "Title (1080p).mp4" without overwriting anything."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from gfgmd.core.archive import read_archive_ids
from gfgmd.core.platform import hidden_window_flags

MEDIA_EXTENSIONS = {"mp4", "mkv", "webm", "m4a", "mp3", "opus", "ogg", "flac", "wav", "mov", "aac"}
AUDIO_EXTENSIONS = {"m4a", "mp3", "opus", "ogg", "flac", "wav", "aac"}
# The extension each audio format saves (yt-dlp's --audio-format names); "best" keeps the site's own.
_AUDIO_FORMAT_EXTENSIONS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "vorbis": "ogg", "flac": "flac", "wav": "wav"}


def format_label(path: str = "", options: dict[str, object] | None = None) -> str:
    """The file type the lists show on a thumbnail ("MP3", "MP4"): the file's own, else the one asked for.

    "" when it isn't known yet (the original audio, kept in whatever format the site sends).
    """
    extension = Path(path).suffix[1:] if path else ""
    if not extension and options:
        if options.get("kind") == "audio":
            extension = _AUDIO_FORMAT_EXTENSIONS.get(str(options.get("audio_format", "mp3")), "")
        else:
            extension = str(options.get("container", "mp4"))
    return extension.upper()


# The original script's staged names, kept for the recovery sweep: an optional "001 - " playlist number, the
# title, the bracketed ID, and the requested resolution.
STAGED_VIDEO_NAME = re.compile(
    r"^(?:\d{3,} - )?(?P<title>.+) \[(?P<id>[A-Za-z0-9_-]{11})\]"
    r"(?: \(requested-\d+p\))?\.mp4$"
)
# The marker this version's templates put after the title: " [<id>] (requested-<profile>)".
_STAGED_TAIL = re.compile(r"^(?P<stem>.+) \[(?P<id>[^\[\]]{1,64})\](?: \(requested-[a-z0-9-]{1,24}\))?$")


def video_quality(video: Path, ffprobe: str) -> int:
    """Read the shorter video dimension from a completed file."""
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=False,
        creationflags=hidden_window_flags(),
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {video}: {result.stderr.strip()}")
    try:
        width, height = (int(value) for value in result.stdout.strip().split(",")[:2])
    except ValueError as exc:
        raise RuntimeError(f"ffprobe returned no video dimensions for {video}") from exc
    if width < 1 or height < 1:
        raise RuntimeError(f"ffprobe returned invalid video dimensions for {video}")
    return min(width, height)


def inside_root(path: Path, root: Path) -> bool:
    """True when `path` resolves inside `root`, so a rename can never leave the download folder.

    The text is compared first, so a path elsewhere (a network share a site's title named) is never
    opened to resolve it; then links are followed, so none leads out of the folder.
    """
    def under(child: str, base: str) -> bool:
        return os.path.normcase(child).startswith(os.path.normcase(base).rstrip("\\/") + os.sep)

    if not under(os.path.abspath(str(path)), os.path.abspath(str(root))):
        return False
    try:
        return under(str(path.resolve()), str(root.resolve()))
    except OSError:
        return False


def clean_stem(staged_stem: str) -> str:
    """The staged stem without its " [id] (requested-...)" marker; unchanged when it has none."""
    match = _STAGED_TAIL.fullmatch(staged_stem)
    return match.group("stem") if match else staged_stem


def unique_target(folder: Path, stem: str, label: str, extension: str, occupied: set[str]) -> Path:
    """The first free "stem[ (n)][ label].ext" in folder; `occupied` holds casefolded names."""
    suffix = f" {label}" if label else ""
    target = folder / f"{stem}{suffix}.{extension}"
    number = 2
    while target.exists() or target.name.casefold() in occupied:
        target = folder / f"{stem} ({number}){suffix}.{extension}"
        number += 1
    return target


def finalize_file(staged: Path, root: Path, ffprobe: str, label_quality: bool) -> Path:
    """Rename a finished download (and its subtitle files) to its clean name; returns the new path.

    The quality label is read from the file itself, so a 1080p request that was only offered at
    720p ends in "(720p)". A file outside `root`, or one without the staged marker, is left alone.
    """
    if not inside_root(staged, root) or not staged.is_file():
        return staged
    extension = staged.suffix[1:].lower()
    stem = clean_stem(staged.stem)
    if stem == staged.stem:
        return staged
    label = ""
    if label_quality and extension not in AUDIO_EXTENSIONS:
        label = f"({video_quality(staged, ffprobe)}p)"
    folder = staged.parent
    occupied = {entry.name.casefold() for entry in folder.iterdir()}
    occupied.discard(staged.name.casefold())
    target = unique_target(folder, stem, label, staged.suffix[1:], occupied)
    sidecars = [entry for entry in folder.iterdir()
                if entry != staged and entry.name.startswith(staged.stem + ".") and entry.is_file()]
    staged.rename(target)
    new_stem = target.stem
    for sidecar in sidecars:
        rest = sidecar.name[len(staged.stem):]  # ".en.srt", ".jpg"
        destination = folder / f"{new_stem}{rest}"
        try:
            if not destination.exists():
                sidecar.rename(destination)
        except OSError:
            continue  # held open (a virus scan, a player): it keeps its old name, the file is saved
    return target


def normalize_downloads(output_root: Path, archive: Path, ffprobe: str) -> int:
    """Name archived MP4s by title and measured quality without collisions (the original script's sweep).

    The app and the command-line tool rename each file as yt-dlp reports it; this sweep catches
    files a crash or the original script left with their staged names.
    """
    if not archive.exists():
        return 0
    archived_ids = read_archive_ids(archive)
    renamed = 0
    # Single downloads sit in the root, lists in folders of their own; the app's dot folders hold no downloads.
    folders = [output_root, *(entry for entry in output_root.iterdir()
                              if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith("."))]
    for media_dir in folders:
        occupied = {entry.name.casefold() for entry in media_dir.iterdir()}
        for video in sorted(media_dir.glob("*.mp4")):
            match = STAGED_VIDEO_NAME.fullmatch(video.name)
            if match is None or match.group("id") not in archived_ids:
                continue
            title = match.group("title")
            quality = video_quality(video, ffprobe)
            target = unique_target(media_dir, title, f"({quality}p)", "mp4", occupied - {video.name.casefold()})
            video.rename(target)
            occupied.remove(video.name.casefold())
            occupied.add(target.name.casefold())
            renamed += 1
    return renamed


_PARTIAL_STEM = re.compile(r"^(?P<stem>.+ \[[^\[\]]{1,64}\](?: \(requested-[a-z0-9-]{1,24}\))?)")


def remove_partials(partials: set[str], incomplete: Path) -> int:
    """Delete a cancelled download's unfinished files; returns how many were removed.

    yt-dlp keeps everything unfinished (parts, fragments, unmerged streams) in the `.incomplete`
    folder until it moves the finished file out, so every file there that shares a reported partial's
    "title [id] (requested-...)" stem belongs to the cancelled download. Nothing outside that folder
    is touched.
    """
    removed = 0
    for partial in partials:
        path = Path(partial)
        match = _PARTIAL_STEM.match(path.name)
        if match is None or not path.parent.is_dir() or not inside_root(path, incomplete):
            continue
        stem = match.group("stem")
        for candidate in path.parent.iterdir():
            if candidate.is_file() and candidate.name.startswith(stem):
                try:
                    candidate.unlink()
                    removed += 1
                except OSError:
                    continue
    return removed


def group_of(path: Path, root: Path | None) -> tuple[str, str]:
    """The playlist or channel folder a saved file is in: (key, title), or ("", "") for one in the root.

    The key is the folder's whole path, case-folded as Windows ignores case; the title is its path
    under the download root, such as "Naseebo Lal" or "Channel · Videos".
    """
    if root is None:
        return "", ""
    folder = path.parent
    try:
        relative = folder.relative_to(root)
    except ValueError:
        return "", ""
    if not relative.parts:
        return "", ""
    return str(folder).casefold(), " · ".join(relative.parts)
