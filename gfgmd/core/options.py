"""Download options: one validated value object shared by the command line, the app, and presets."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Literal
from urllib.parse import urlparse

from gfgmd.config.defaults import DownloadDefaults, FormatDefaults

# "photo" is a gallery-dl download of a post's or a picture site's pictures (see core/gallery.py).
Kind = Literal["video", "audio", "photo"]
_LANGS = re.compile(r"^[A-Za-z0-9_.*,-]{1,2000}$")
_ITEMS = re.compile(r"^[0-9:,\- ]{1,500}$")
# A language code as sites report audio tracks: "en", "es-419", "pt-BR".
_LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,2}$")
MAX_AUDIO_TRACKS = 12
_PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
_SPONSOR_CATEGORIES = {code for _, code in FormatDefaults.SPONSORBLOCK_CATEGORIES}
# One part of a time: the leading parts are whole numbers, the seconds may have a fraction.
_TIME_LEAD = re.compile(r"^\d{1,3}$")
_TIME_SECONDS = re.compile(r"^\d{1,6}(?:\.\d{1,3})?$")
_TIME_HELP = "Type times as minutes and seconds, such as 1:30, or with hours, such as 1:02:30."


_TUPLE_FIELDS = {"sponsorblock_categories", "audio_langs"}


def _gone(choice: str) -> str:
    """The message for a saved choice the app no longer offers (an old preset, a hand-edited file)."""
    return f"The {choice} you chose isn't available any more. Pick another one."


@dataclass(frozen=True)
class DownloadOptions:
    """How one download is saved. The defaults reproduce the original script's command-line behavior."""

    kind: Kind = "video"
    # The highest resolution on the shorter side of the video; 0 means no limit.
    max_height: int = 1080
    container: str = "mp4"
    codec_profile: str = "balanced"
    # "original" keeps one audio track in the video's own language; "languages" and "all" add the
    # tracks listed in audio_langs (dubbed languages), which needs MP4 or MKV.
    audio_tracks: str = "original"
    audio_langs: tuple[str, ...] = ()
    audio_format: str = "mp3"
    # kbps for lossy audio formats; ignored for FLAC, WAV, and the original stream.
    audio_quality: int = FormatDefaults.DEFAULT_AUDIO_QUALITY
    # The shape of the cover embedded in audio files.
    cover: str = "square"
    subtitles: str = "none"
    subtitle_format: str = "srt"
    subtitle_langs: str = "en.*"
    auto_subtitles: bool = False
    # Audio downloads save timed lyrics (.lrc): the site's captions first, then an LRCLIB lookup.
    lyrics: bool = True
    lyrics_online: bool = True
    embed_thumbnail: bool = False
    embed_metadata: bool = False
    embed_chapters: bool = False
    sponsorblock: str = "off"
    sponsorblock_categories: tuple[str, ...] = ("sponsor", "selfpromo", "interaction")
    filename_style: str = "title-quality"
    fragments: int = DownloadDefaults.AUTO_FRAGMENTS
    # Bytes per second for this download's process; 0 means no limit.
    limit_rate: int = 0
    proxy: str = ""
    force_ipv4: bool = False
    # A yt-dlp --playlist-items selection such as "1:5,8"; "" downloads every item.
    items: str = ""
    live_from_start: bool = False
    wait_for_video: bool = False
    # Download even what the archive lists as downloaded before ("Download again").
    ignore_archive: bool = False
    # Only part of the video, from `section_start` to `section_end` (see parse_time); both "" for the
    # whole video, and an empty end runs to the end.
    section_start: str = ""
    section_end: str = ""
    # Cut the part at the exact times, which re-encodes it (slower), instead of at the nearest keyframes.
    exact_cut: bool = False
    # One file per chapter of the video, in a folder named after it; the whole file isn't kept.
    split_chapters: bool = False
    # A video download of a post on a picture site saves the post's pictures too (core/gallery.py).
    save_photos: bool = True

    def validate(self) -> DownloadOptions:
        """Return self, or raise ValueError naming the first value that can't be used."""
        if self.kind not in ("video", "audio", "photo"):
            raise ValueError("Choose Video or Audio only as the type.")
        if self.max_height < 0 or self.max_height > 10000:
            raise ValueError(_gone("quality"))
        if self.container not in FormatDefaults.CONTAINERS:
            raise ValueError(_gone("file type"))
        if self.codec_profile not in FormatDefaults.CODEC_PROFILES:
            raise ValueError(_gone("compatibility setting"))
        if self.audio_format not in FormatDefaults.AUDIO_FORMATS:
            raise ValueError(_gone("audio format"))
        if self.audio_quality not in FormatDefaults.AUDIO_QUALITIES:
            raise ValueError(_gone("audio quality"))
        if self.cover not in FormatDefaults.COVER_SHAPES:
            raise ValueError(_gone("cover shape"))
        if self.audio_tracks not in FormatDefaults.AUDIO_TRACK_MODES:
            raise ValueError(_gone("audio track setting"))
        if self.kind == "video" and self.audio_tracks != "original":
            if not self.audio_langs:
                raise ValueError("Choose at least one more audio language, or keep the original language only.")
            if len(self.audio_langs) > MAX_AUDIO_TRACKS:
                raise ValueError(f"Choose at most {MAX_AUDIO_TRACKS} audio languages.")
            bad = [code for code in self.audio_langs if not _LANG_CODE.fullmatch(code)]
            if bad:
                raise ValueError(f"\"{bad[0]}\" isn't a language code. Type short codes that look like es or pt-BR, "
                                 "separated by commas.")
            if self.container not in ("mp4", "mkv"):
                raise ValueError("To keep more than one language, choose MP4 or MKV as the file type.")
        if self.subtitle_format not in FormatDefaults.SUBTITLE_FORMATS:
            raise ValueError(_gone("subtitle file type"))
        if self.subtitles not in FormatDefaults.SUBTITLE_MODES:
            raise ValueError(_gone("subtitle setting"))
        if self.subtitles != "none" and not _LANGS.fullmatch(self.subtitle_langs):
            raise ValueError("Type subtitle languages as short codes separated by commas, without spaces, "
                             "such as en.*,ur.")
        if self.sponsorblock not in FormatDefaults.SPONSORBLOCK_MODES:
            raise ValueError(_gone("SponsorBlock setting"))
        if self.sponsorblock != "off":
            unknown = [cat for cat in self.sponsorblock_categories if cat not in _SPONSOR_CATEGORIES]
            if unknown or not self.sponsorblock_categories:
                raise ValueError("Pick at least one kind of part for SponsorBlock to mark or cut.")
        if self.filename_style not in DownloadDefaults.FILENAME_STYLES:
            raise ValueError(_gone("file name style"))
        if not 1 <= self.fragments <= DownloadDefaults.MAX_FRAGMENTS:
            raise ValueError(f"Parts at once must be from 1 to {DownloadDefaults.MAX_FRAGMENTS}.")
        if self.limit_rate < 0:
            raise ValueError("The speed limit can't be below zero.")
        if self.proxy:
            check_proxy(self.proxy)
        if self.items and not _ITEMS.fullmatch(self.items):
            raise ValueError("Type the numbers of the videos to download, such as 1:5,8 (1 to 5, and 8).")
        if self.has_section:
            start, end = self.section
            if end is not None and end <= start:
                raise ValueError("The part has to end after it starts.")
            if self.split_chapters:
                raise ValueError("Download a part, or split the video into chapters, but not both at once.")
            if self.live_from_start:
                raise ValueError("A live stream can't be downloaded in part. Download it whole.")
        return self

    def to_dict(self) -> dict[str, Any]:
        """The options as JSON-ready data (tuples become lists)."""
        data = asdict(self)
        data["sponsorblock_categories"] = list(self.sponsorblock_categories)
        data["audio_langs"] = list(self.audio_langs)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownloadOptions:
        """Options from saved data, ignoring unknown keys and keeping the defaults for missing ones."""
        known = {item.name: item for item in fields(cls)}
        values: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            if key in _TUPLE_FIELDS:
                if isinstance(value, (list, tuple)) and all(isinstance(entry, str) for entry in value):
                    values[key] = tuple(value)
                continue
            default = getattr(cls(), key)
            if isinstance(default, bool) != isinstance(value, bool):
                continue
            if isinstance(value, type(default)):
                values[key] = value
        return cls(**values).validate()

    def with_changes(self, **changes: Any) -> DownloadOptions:
        """A copy with some values replaced, validated."""
        return replace(self, **changes).validate()

    @property
    def has_section(self) -> bool:
        """True when only part of the video downloads."""
        return bool(self.section_start or self.section_end)

    @property
    def section(self) -> tuple[float, float | None]:
        """The part's start and end in seconds; the end is None when it runs to the end of the video."""
        start = parse_time(self.section_start) if self.section_start else 0.0
        return start, (parse_time(self.section_end) if self.section_end else None)

    @property
    def section_label(self) -> str:
        """The part as its file name says it: "1m23s-4m05s", or "1m23s-end"."""
        start, end = self.section
        return f"{clock_label(start)}-{clock_label(end) if end is not None else 'end'}"

    @property
    def multi_audio(self) -> bool:
        """True when a video keeps dubbed audio tracks next to the original."""
        return self.kind == "video" and self.audio_tracks != "original" and bool(self.audio_langs)

    @property
    def lossless_audio(self) -> bool:
        """True when the audio format has no bitrate to choose (FLAC, WAV, or the original stream)."""
        return self.audio_format in FormatDefaults.LOSSLESS_AUDIO

    @property
    def profile(self) -> str:
        """The archive suffix: "1080p" or "best" for MP4 video (the original script's names, so its archives
        still match), "best-mkv" or "720p-webm" for the other file types, which are files of their own;
        "audio-mp3-320k" or "audio-flac" for audio. A part ends in "-part" and chapters in "-ch", since
        they are files of their own too."""
        if self.kind == "photo":
            return "photos"
        if self.kind == "audio":
            base = f"audio-{self.audio_format}" if self.lossless_audio else f"audio-{self.audio_format}-{self.audio_quality}k"
        else:
            quality = f"{self.max_height}p" if self.max_height else "best"
            base = quality if self.container == "mp4" else f"{quality}-{self.container}"
        return base + ("-part" if self.has_section else "-ch" if self.split_chapters else "")

    @property
    def extension(self) -> str:
        """The file extension a download with these options ends in ("" when the site decides: Original audio)."""
        if self.kind == "audio":
            return {"vorbis": "ogg", "best": ""}.get(self.audio_format, self.audio_format)
        if self.kind == "photo":
            return ""  # the site's own picture formats
        return self.container


def parse_time(text: str) -> float:
    """Seconds from a time typed as seconds ("90"), minutes and seconds ("1:30"), or with hours
    ("1:02:30"); the seconds may have a fraction ("1:30.5"). Raises ValueError with what to type."""
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3 or not _TIME_SECONDS.fullmatch(parts[-1]) \
            or not all(_TIME_LEAD.fullmatch(part) for part in parts[:-1]):
        raise ValueError(_TIME_HELP)
    numbers = [float(part) for part in parts]
    if any(number >= 60 for number in numbers[1:]):
        raise ValueError(_TIME_HELP)
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def clock_label(seconds: float) -> str:
    """A time for a file name, without colons: "45s", "1m23s", "1h02m03s"."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def check_proxy(proxy: str) -> str:
    """Return a proxy URL yt-dlp accepts, or raise ValueError."""
    parsed = urlparse(proxy)
    if parsed.scheme not in _PROXY_SCHEMES or not parsed.hostname:
        raise ValueError("Type the proxy address with its port, such as http://proxy:8080 or socks5://proxy:1080.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("The proxy's port must be a number, such as 8080.") from exc
    return proxy
