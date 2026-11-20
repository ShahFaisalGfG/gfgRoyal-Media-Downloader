"""Download options: one validated value object shared by the command line, the app, and presets."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Literal
from urllib.parse import urlparse

from gfgmd.config.defaults import DownloadDefaults, FormatDefaults

Kind = Literal["video", "audio"]
_LANGS = re.compile(r"^[A-Za-z0-9_.*,-]{1,200}$")
_ITEMS = re.compile(r"^[0-9:,\- ]{1,500}$")
# A language code as sites report audio tracks: "en", "es-419", "pt-BR".
_LANG_CODE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,2}$")
MAX_AUDIO_TRACKS = 12
_PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
_SPONSOR_CATEGORIES = {code for _, code in FormatDefaults.SPONSORBLOCK_CATEGORIES}


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

    def validate(self) -> DownloadOptions:
        """Return self, or raise ValueError naming the first value that can't be used."""
        if self.kind not in ("video", "audio"):
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
        "audio-mp3-320k" or "audio-flac" for audio."""
        if self.kind == "audio":
            if self.lossless_audio:
                return f"audio-{self.audio_format}"
            return f"audio-{self.audio_format}-{self.audio_quality}k"
        quality = f"{self.max_height}p" if self.max_height else "best"
        return quality if self.container == "mp4" else f"{quality}-{self.container}"

    @property
    def extension(self) -> str:
        """The file extension a download with these options ends in ("" when the site decides: Original audio)."""
        if self.kind == "audio":
            return {"vorbis": "ogg", "best": ""}.get(self.audio_format, self.audio_format)
        return self.container


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


def options_from_preset(preset: dict[str, Any], base: DownloadOptions) -> DownloadOptions:
    """Apply a preset's values (kind, resolution, container, codec, audio format) on top of `base`."""
    keys = {"kind", "max_height", "container", "codec_profile", "audio_tracks", "audio_langs", "audio_format",
            "audio_quality", "cover", "subtitles", "subtitle_format", "sponsorblock", "lyrics"}
    changes = {key: value for key, value in preset.items() if key in keys}
    return DownloadOptions.from_dict({**base.to_dict(), **changes})
