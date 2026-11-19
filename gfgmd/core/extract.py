"""Extract the sound of a downloaded video into an audio file, saved the way an audio download is.

Extract audio runs as a queue job: the audio format and bitrate, cover, tags, and lyrics from
Preferences, made from the video on disk instead of downloading the song again. The cover is the
thumbnail the video holds (or the list's cached one), the tags are the video's with the artist
cleaned up as audio downloads clean it, and lyrics come from the video's caption files, then
LRCLIB. Stdlib only, so the command-line tool can share it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from gfgmd.config.defaults import FormatDefaults
from gfgmd.core.captions import parse_file, sidecars, to_lrc
from gfgmd.core.command import ARTIST_SUFFIX, ARTIST_TITLE, SQUARE_CROP
from gfgmd.core.errors import CATEGORIES, Failure
from gfgmd.core.jobs import JobResult, Runner
from gfgmd.core.lyrics import Fetch, add_lyrics
from gfgmd.core.naming import finalize_file
from gfgmd.core.options import DownloadOptions
from gfgmd.core.platform import hidden_window_flags
from gfgmd.core.progress import Snapshot
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet

# ffmpeg's encoder for each audio format the app offers (yt-dlp's --audio-format names).
ENCODERS = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus", "vorbis": "libvorbis", "flac": "flac",
            "wav": "pcm_s16le"}
# Where "Original (no conversion)" keeps each codec; any other track is kept lossless as FLAC.
ORIGINAL_CONTAINERS = {"aac": "m4a", "alac": "m4a", "mp3": "mp3", "opus": "opus", "vorbis": "ogg", "flac": "flac"}
# Tags carried over from the video; the technical ones (encoder, brands) are left behind.
KEPT_TAGS = ("title", "artist", "album_artist", "album", "date", "genre", "track", "composer", "comment",
             "description", "synopsis", "purl", "copyright", "language")
# A cover larger than this isn't a thumbnail; the audio is saved without it.
MAX_COVER_BYTES = 8 * 1024 * 1024
_QUALITY_LABEL = re.compile(r"\s*\(\d{3,4}p\)$")
_ARTIST_TITLE = re.compile(ARTIST_TITLE)
_ARTIST_NOISE = re.compile(ARTIST_SUFFIX)
_FFMETADATA_SPECIAL = re.compile(r"([=;#\\\n])")
_TIMEOUT = 120


class ExtractError(RuntimeError):
    """The video couldn't be read or its cover couldn't be prepared."""


@dataclass(frozen=True)
class VideoProbe:
    """What ffprobe reads from a video."""

    duration: float = 0.0
    audio_stream: int = -1  # the original sound track's stream index, -1 when there is none
    audio_codec: str = ""
    cover_stream: int = -1  # the thumbnail embedded as a picture stream (MP4)
    attachment_stream: int = -1  # the thumbnail attached as a file (MKV)
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractSpec:
    """One video whose sound becomes an audio file."""

    video: Path
    options: DownloadOptions
    root: Path  # the audio download folder
    folder: str  # the subfolder of `root` it goes in, mirroring the video's ("YouTube/Single Videos")
    scratch: Path  # the job's scratch folder, for the cover and the tag list
    item_id: str = ""  # the video's ID on its site, which marks the unfinished file
    title: str = ""
    uploader: str = ""
    url: str = ""
    thumbnail: str = ""  # the thumbnail's link, shown in the list
    cover_hint: Path | None = None  # a cached copy of the thumbnail, used when the video holds none

    @property
    def incomplete(self) -> Path:
        """Where the audio is written until it is complete, as downloads are."""
        return self.root / ".incomplete"


def read_probe(data: dict[str, Any]) -> VideoProbe:
    """The parts of ffprobe's JSON this step uses."""
    streams = [stream for stream in data.get("streams") or [] if isinstance(stream, dict)]

    def flag(stream: dict[str, Any], name: str) -> bool:
        disposition = stream.get("disposition")
        return isinstance(disposition, dict) and bool(disposition.get(name))

    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    # The default track is the original one; yt-dlp also puts the original first.
    chosen = next((stream for stream in audio if flag(stream, "default")), audio[0] if audio else None)
    cover = next((stream for stream in streams if stream.get("codec_type") == "video" and flag(stream, "attached_pic")),
                 None)
    attachment = next((stream for stream in streams if stream.get("codec_type") == "attachment"
                       and str((stream.get("tags") or {}).get("mimetype", "")).startswith("image/")), None)
    container = data.get("format")
    container = container if isinstance(container, dict) else {}
    raw_tags = container.get("tags")
    raw_tags = raw_tags if isinstance(raw_tags, dict) else {}
    tags = {str(key).lower(): str(value) for key, value in raw_tags.items() if str(key).lower() in KEPT_TAGS and value}
    try:
        duration = float(container.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    def index(stream: dict[str, Any] | None) -> int:
        return int(stream.get("index", -1)) if stream else -1

    return VideoProbe(duration, index(chosen), str(chosen.get("codec_name", "")) if chosen else "", index(cover),
                      index(attachment), tags)


def probe_video(ffprobe: str, video: Path) -> VideoProbe:
    """Read a video's length, sound tracks, embedded thumbnail, and tags; raises ExtractError."""
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
                                timeout=_TIMEOUT, creationflags=hidden_window_flags())
        data = json.loads(result.stdout or "{}") if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ExtractError(f"ffprobe couldn't read the video: {error}") from error
    if not isinstance(data, dict):
        raise ExtractError("ffprobe couldn't read the video; it may be damaged or still in use")
    return read_probe(data)


def audio_encoding(options: DownloadOptions, source_codec: str) -> tuple[str, list[str]]:
    """The file extension and ffmpeg's audio arguments for the chosen format and bitrate."""
    audio_format = options.audio_format
    if audio_format == "best":
        container = ORIGINAL_CONTAINERS.get(source_codec)
        if container:
            return container, ["-c:a", "copy"]
        audio_format = "flac"
    args = ["-c:a", ENCODERS[audio_format]]
    if audio_format not in FormatDefaults.LOSSLESS_AUDIO:
        args += ["-b:a", f"{options.audio_quality}k"]
    return FormatDefaults.AUDIO_EXTENSIONS[audio_format], args


def audio_stem(video: Path) -> str:
    """The audio's name: the video's, without its quality label ("Song (1080p)" becomes "Song")."""
    return _QUALITY_LABEL.sub("", video.stem) or video.stem


def song_tags(probe: VideoProbe, title: str, uploader: str, url: str) -> dict[str, str]:
    """The audio's tags: the video's own, with the artist cleaned up as audio downloads clean it.

    An "Artist - Song | labels" title names the artist and the song when the site named no artist
    of its own (the video's artist tag is then only its uploading channel).
    """
    tags = dict(probe.tags)
    channel = uploader.strip()
    artist = tags.get("artist", "").strip()
    named = bool(artist) and artist.casefold() not in (channel.casefold(), _ARTIST_NOISE.sub("", channel).casefold())
    tags["title"] = tags.get("title") or title
    tags["artist"] = _ARTIST_NOISE.sub("", artist or channel).strip()
    match = None if named else _ARTIST_TITLE.match(tags["title"])
    if match:
        tags["artist"], tags["title"] = match.group("meta_artist").strip(), match.group("meta_title").strip()
    if url:
        tags.setdefault("purl", url)
        tags.setdefault("comment", url)
    return {key: value for key, value in tags.items() if value}


def picture_block(image: bytes, mime: str = "image/jpeg") -> str:
    """A front cover as a FLAC picture block in base64, the way Ogg and Opus files carry one."""
    kind = mime.encode("ascii")
    block = (struct.pack(">II", 3, len(kind)) + kind + struct.pack(">I", 0)
             + struct.pack(">IIIII", 0, 0, 0, 0, len(image)) + image)
    return base64.b64encode(block).decode("ascii")


def ffmetadata(tags: dict[str, str]) -> str:
    """Tags in ffmpeg's metadata file format (read with -f ffmetadata), which has no length limit."""
    def escape(text: str) -> str:
        return _FFMETADATA_SPECIAL.sub(r"\\\1", text)

    return "".join([";FFMETADATA1\n", *(f"{escape(key)}={escape(value)}\n" for key, value in tags.items())])


def extract_command(ffmpeg: str, video: Path, probe: VideoProbe, options: DownloadOptions, metadata: Path | None,
                    cover: Path | None, target: Path, codec_args: list[str]) -> list[str]:
    """The ffmpeg command that writes the audio with its tags (from `metadata`), chapters, and cover."""
    extension = target.suffix[1:].lower()
    embeds_cover = cover is not None and extension in ("mp3", "m4a", "flac")
    command = [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y", "-progress", "pipe:1", "-nostats",
               "-i", str(video)]
    if metadata is not None:
        command += ["-f", "ffmetadata", "-i", str(metadata)]
    if embeds_cover:
        command += ["-i", str(cover)]
    command += ["-map", f"0:{probe.audio_stream}"]
    if embeds_cover:
        cover_input = 2 if metadata is not None else 1
        command += ["-map", f"{cover_input}:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        if extension == "mp3":
            command += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    command += ["-map_metadata", "1" if metadata is not None else "-1",
                "-map_chapters", "0" if options.embed_chapters and extension != "wav" else "-1"]
    command += codec_args
    if extension == "mp3":
        command += ["-id3v2_version", "3"]  # what yt-dlp writes for an MP3 with a cover; Windows reads it best
    return command + [str(target)]


class AudioExtractor:
    """Extract one video's audio; call run() on a worker thread and stop() from any thread.

    It offers the queue what JobExecutor does (run, stop, snapshot, partial_files), so the queue runs
    it as one of its jobs.
    """

    def __init__(self, spec: ExtractSpec, tools: Callable[[], ToolSet],
                 on_file: Callable[[dict[str, Any], Path], None] | None = None, runner: Runner = run_to_completion,
                 lyrics_fetch: Fetch | None = None, probe: Callable[[str, Path], VideoProbe] | None = None) -> None:
        self._spec = spec
        self._tools = tools
        self._on_file = on_file
        self._runner = runner
        # How lyrics are looked up online (lyrics.fetch_json); None uses the video's captions only.
        self._lyrics_fetch = lyrics_fetch
        self._probe = probe  # probe_video unless a test reads the video another way
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snap = Snapshot(title=spec.title, thumbnail=spec.thumbnail)
        self._duration = 0.0
        self._errors: list[str] = []
        self._partials: set[str] = set()

    def stop(self) -> None:
        """Stop the extraction."""
        self._stop.set()

    def snapshot(self) -> Snapshot:
        """The current progress."""
        with self._lock:
            return replace(self._snap)

    def partial_files(self) -> set[str]:
        """The unfinished audio file (for removing a cancelled extraction)."""
        with self._lock:
            return set(self._partials)

    def run(self) -> JobResult:
        """Extract the audio; never raises for a damaged video, a missing tool, or a full disk."""
        spec = self._spec
        result = JobResult("failed", attempts=1)
        try:
            tools = self._tools()
        except RuntimeError as error:
            result.failure = Failure(CATEGORIES["tools"], str(error))
            return result
        if not spec.video.is_file():
            result.failure = Failure(CATEGORIES["source_missing"], str(spec.video))
            return result
        try:
            probe = (self._probe or probe_video)(tools.ffprobe, spec.video)
        except ExtractError as error:
            result.failure = Failure(CATEGORIES["postprocess"], str(error))
            return result
        if probe.audio_stream < 0:
            result.failure = Failure(CATEGORIES["no_audio"], str(spec.video))
            return result
        self._duration = probe.duration
        try:
            final = self._convert(tools, probe, result)
        except OSError as error:
            result.failure = Failure(CATEGORIES["access_denied"], str(error))
            return result
        finally:
            shutil.rmtree(spec.scratch / "extract", ignore_errors=True)
        if final is None:
            return result
        if spec.options.lyrics:
            self._set_stage("Adding lyrics")
            self._add_lyrics(final, tools, probe)
        result.state = "done"
        result.files.append(final)
        if self._on_file is not None:
            self._on_file({"id": spec.item_id, "title": spec.title or final.stem, "uploader": spec.uploader,
                           "webpage_url": spec.url, "duration": probe.duration}, final)
        return result

    def _convert(self, tools: ToolSet, probe: VideoProbe, result: JobResult) -> Path | None:
        """Write the audio into the unfinished folder, then move it into place; None when it failed."""
        spec = self._spec
        work = spec.scratch / "extract"
        work.mkdir(parents=True, exist_ok=True)
        extension, codec_args = audio_encoding(spec.options, probe.audio_codec)
        cover = self._cover(tools, probe, work) if spec.options.embed_thumbnail else None
        tags = song_tags(probe, spec.title, spec.uploader, spec.url) if spec.options.embed_metadata else {}
        if cover is not None and extension in ("opus", "ogg"):
            tags["METADATA_BLOCK_PICTURE"] = picture_block(cover.read_bytes())
        metadata = work / "tags.txt" if tags else None
        if metadata is not None:
            metadata.write_text(ffmetadata(tags), encoding="utf-8")
        marker = re.sub(r"[\[\]]", "", spec.item_id)[:64] or "local"
        name = f"{audio_stem(spec.video)} [{marker}] (requested-{spec.options.profile}).{extension}"
        staged = spec.incomplete / spec.folder / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._partials.add(str(staged))
        self._set_stage("Extracting audio")
        command = extract_command(tools.ffmpeg, spec.video, probe, spec.options, metadata, cover, staged, codec_args)
        code, stopped = self._runner(command, self._feed, self._stop)
        if stopped or self._stop.is_set():
            result.state = "stopped"
            return None
        if code != 0 or not staged.is_file():
            staged.unlink(missing_ok=True)
            detail = self._errors[-1] if self._errors else f"ffmpeg exited with status {code}"
            if any("No space left" in line for line in self._errors):
                result.state, result.failure = "disk_full", Failure(CATEGORIES["disk_full"], detail)
            else:
                result.failure = Failure(CATEGORIES["postprocess"], detail)
            return None
        placed = spec.root / spec.folder / name
        placed.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, placed)
        with self._lock:
            self._partials.discard(str(staged))
        final = finalize_file(placed, spec.root, tools.ffprobe, label_quality=False)
        if cover is not None and extension == "wav":
            # WAV can't hold a cover, so it is saved beside the song, as audio downloads save it.
            shutil.copyfile(cover, final.with_suffix(".jpg"))
        return final

    def _cover(self, tools: ToolSet, probe: VideoProbe, work: Path) -> Path | None:
        """The cover as a JPEG (square when chosen): the video's thumbnail, else the cached one."""
        spec = self._spec
        source: list[str] = []
        if probe.cover_stream >= 0:
            source = ["-i", str(spec.video), "-map", f"0:{probe.cover_stream}"]
        elif probe.attachment_stream >= 0:
            attached = work / "attached"
            # ffmpeg writes an attachment out only while it reads the file; the null output reads nothing.
            subprocess.run([tools.ffmpeg, "-v", "error", "-y", f"-dump_attachment:{probe.attachment_stream}",
                            str(attached), "-i", str(spec.video), "-t", "0", "-f", "null", "-"],
                           capture_output=True, check=False, timeout=_TIMEOUT, creationflags=hidden_window_flags())
            if attached.is_file():
                source = ["-i", str(attached)]
        if not source and spec.cover_hint is not None and spec.cover_hint.is_file():
            source = ["-i", str(spec.cover_hint)]
        if not source:
            return None
        target = work / "cover.jpg"
        crop = ["-vf", SQUARE_CROP] if spec.options.cover == "square" else []
        try:
            done = subprocess.run([tools.ffmpeg, "-v", "error", "-y", *source, "-frames:v", "1", *crop, "-c:v", "mjpeg",
                                   "-qmin", "1", "-q:v", "1", str(target)],
                                  capture_output=True, check=False, timeout=_TIMEOUT, creationflags=hidden_window_flags())
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode != 0 or not target.is_file() or target.stat().st_size > MAX_COVER_BYTES:
            return None  # the audio is still worth having without its cover
        return target

    def _add_lyrics(self, audio: Path, tools: ToolSet, probe: VideoProbe) -> None:
        """The video's caption files become the song's timed lyrics; LRCLIB fills in when there are none."""
        spec = self._spec
        stem = spec.video.stem
        for caption in sidecars(spec.video):
            language = caption.stem[len(stem) + 1:] if caption.stem.startswith(stem + ".") else ""
            cues = parse_file(caption) if language and caption.suffix.lower() != ".lrc" else []
            if cues:
                try:
                    (audio.parent / f"{audio.stem}.{language}.lrc").write_text(to_lrc(cues), encoding="utf-8")
                except OSError:
                    continue  # this language is skipped; another one or LRCLIB may still fit
        info = {"title": spec.title, "uploader": spec.uploader, "duration": probe.duration,
                "album": probe.tags.get("album", "")}
        artist = probe.tags.get("artist", "")
        if artist and artist.casefold() != spec.uploader.casefold():
            info["artist"] = artist
        online = spec.options.lyrics_online and self._lyrics_fetch is not None
        add_lyrics(audio, info, spec.options.subtitle_langs, online, tools.ffmpeg, tools.ffprobe,
                   self._lyrics_fetch or (lambda _url: None))

    def _set_stage(self, stage: str) -> None:
        with self._lock:
            self._snap = replace(self._snap, stage=stage)

    def _feed(self, stream: str, line: str) -> None:
        """Read ffmpeg's progress lines (out_time_us=, speed=) into the snapshot; keep its error lines."""
        if stream == "err":
            if line.strip():
                self._errors = [*self._errors[-9:], line.strip()]
            return
        key, _, value = line.strip().partition("=")
        with self._lock:
            if key in ("out_time_us", "out_time_ms") and value.isdigit() and self._duration > 0:
                # Both keys count microseconds; ffmpeg kept the old name for compatibility.
                done = min(int(value) / 1_000_000, self._duration)
                self._snap = replace(self._snap, overall=done / self._duration, item_fraction=done / self._duration)
            elif key == "speed" and value.endswith("x"):
                try:
                    speed = float(value[:-1])
                except ValueError:
                    return
                left = self._duration * (1 - self._snap.overall)
                self._snap = replace(self._snap, eta=int(left / speed) if speed > 0 else -1)
