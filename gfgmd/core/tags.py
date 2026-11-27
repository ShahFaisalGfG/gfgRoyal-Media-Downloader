"""Retag a saved song or video in place, keeping every stream: a chapter's own title and track number,
or a Spotify song's title, artists, album, and cover.

FFmpeg copies the file with the new tags (no re-encoding) beside it, and the copy replaces the file
only when every stream came through.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from gfgmd.core.platform import hidden_window_flags

_TIMEOUT = 300
# Formats whose tags live with the audio stream (Vorbis comments) as well as the file.
_STREAM_TAGGED = ("opus", "ogg")
# Formats that hold a cover as an attached picture, which a new cover replaces.
_COVER_FORMATS = ("mp3", "m4a", "flac")


def stream_count(ffprobe: str, path: Path) -> int:
    """How many streams the file holds as ffprobe reads it (-1 when it can't)."""
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=index", "-of", "csv=p=0",
                                 str(path)], capture_output=True, text=True, check=False, timeout=60,
                                creationflags=hidden_window_flags())
    except (OSError, subprocess.SubprocessError):
        return -1
    return len(result.stdout.split()) if result.returncode == 0 else -1


def retag_command(ffmpeg: str, source: Path, target: Path, tags: dict[str, str], cover: Path | None = None) -> list[str]:
    """The FFmpeg command that copies `source` to `target` with these tags changed (the rest kept) and,
    for MP3, M4A, and FLAC, `cover` as its picture in place of the old one."""
    extension = source.suffix[1:].lower()
    new_cover = cover is not None and extension in _COVER_FORMATS
    command = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(source)]
    if new_cover:
        command += ["-i", str(cover), "-map", "0:a", "-map", "1:0", "-disposition:v:0", "attached_pic"]
        if extension == "mp3":
            command += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        command += ["-map", "0"]
    command += ["-c", "copy", "-map_metadata", "0"]
    for key, value in tags.items():
        command += ["-metadata", f"{key}={value}"]
        if extension in _STREAM_TAGGED:
            command += ["-metadata:s:a:0", f"{key}={value}"]
    if extension == "mp3":
        command += ["-id3v2_version", "3"]  # what yt-dlp writes; Windows reads it best
    return command + [str(target)]


def retag(path: Path, tags: dict[str, str], ffmpeg: str, ffprobe: str, cover: Path | None = None) -> bool:
    """Change these tags of a saved file in place (empty values are left alone); True when it worked.
    Never raises: a file that can't be retagged keeps the tags it had."""
    changes = {key: value for key, value in tags.items() if value}
    if not changes and cover is None:
        return True
    temporary = path.with_name(f"{path.stem}.tags-tmp{path.suffix}")
    replaced_cover = cover is not None and path.suffix[1:].lower() in _COVER_FORMATS
    try:
        result = subprocess.run(retag_command(ffmpeg, path, temporary, changes, cover), capture_output=True,
                                check=False, timeout=_TIMEOUT, creationflags=hidden_window_flags())
        if result.returncode != 0:
            return False
        before, after = stream_count(ffprobe, path), stream_count(ffprobe, temporary)
        # A new cover replaces the old picture, so the copy holds the audio plus one picture.
        if after < 1 or (not replaced_cover and after != before):
            return False
        os.replace(temporary, path)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        temporary.unlink(missing_ok=True)
