# defaults.py - application metadata, default preferences, presets, and the option lists shown in the UI
#
# Stdlib only: the command-line tool and the Qt-free core read these values too.

from __future__ import annotations

from typing import Any, Dict


class AppInfo:
    """Application information and metadata."""

    APP_NAME = "gfgRoyal Media Downloader"
    # The name used where spaces get in the way: executables, release files, and mutexes.
    FILE_NAME = "gfgRoyal-Media-Downloader"
    APP_VERSION = "1.0.0"
    APP_AUTHOR = "Shah Faisal"
    APP_DESCRIPTION = "Download and play videos, music, playlists, Shorts, and live streams from YouTube and other sites"
    CLI_NAME = "gfgmd"


class UpdateInfo:
    """Where updates come from, and the keys that sign them (scripts/sign_update.py)."""

    REPO_URL = "https://github.com/ShahFaisalGfG/gfgRoyal-Media-Downloader"
    # The public half of each release signing key, exactly as `openssl ec -pubout` prints it. The
    # release workflow refuses to sign with a key that is not listed here, and the app refuses an
    # update whose signature no listed key verifies. The private half lives in Doppler (project
    # gfgroyal-media-downloader, config prd) and is copied to the UPDATE_SIGNING_KEY Actions secret.
    PUBLIC_KEYS: tuple[str, ...] = (
        """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEmE9nOZHlSekC2pAe8+f67uACbtff
oyB9smRSo81o5hzMlv96+moKAFBzDO4yhcr52s7vgIeMtTUO7L6E361Ihw==
-----END PUBLIC KEY-----
""",
    )


class UpdateDefaults:
    """Default update preferences: check once a day, and install in the background."""

    AUTO_CHECK = True
    AUTO_INSTALL = True


class ThemeDefaults:
    """Theme preferences and the options shown in the picker."""

    DEFAULT_THEME = "system"
    OPTIONS = [
        ("System (follow Windows)", "system"),
        ("Light", "light"),
        ("Dark", "dark"),
    ]
    SUPPORTED_THEMES = [code for _, code in OPTIONS]


class LoggingDefaults:
    """Logging preferences and the options shown in the picker."""

    ENABLE_LOGS = False
    DEFAULT_LOG_LEVEL = "critical"
    OPTIONS = [
        ("Errors only", "critical"),
        ("Everything", "all"),
    ]
    SUPPORTED_LOG_LEVELS = [code for _, code in OPTIONS]


class FormatDefaults:
    """Choices for the video and audio formats a download is saved in."""

    # The highest resolution, measured on the shorter side so portrait videos and Shorts share the
    # same scale; 0 means no limit.
    HEIGHT_OPTIONS = [
        ("Best available", 0),
        ("2160p (4K)", 2160),
        ("1440p", 1440),
        ("1080p", 1080),
        ("720p", 720),
        ("480p", 480),
        ("360p", 360),
    ]
    HEIGHTS = [height for _, height in HEIGHT_OPTIONS]
    CONTAINER_OPTIONS = [
        ("MP4 (plays everywhere)", "mp4"),
        ("MKV (keeps every codec)", "mkv"),
        ("WebM", "webm"),
    ]
    CONTAINERS = [code for _, code in CONTAINER_OPTIONS]
    # Balanced is the original script's order: resolution first, then HLS and H.264/AAC at that resolution.
    CODEC_OPTIONS = [
        ("Compatible (H.264 and AAC first)", "compatible"),
        ("Balanced (resolution first, then H.264)", "balanced"),
        ("Best quality (AV1 and VP9 allowed)", "best"),
    ]
    CODEC_PROFILES = [code for _, code in CODEC_OPTIONS]
    # Which audio tracks a video keeps. Sites such as YouTube offer dubbed tracks next to the original.
    AUDIO_TRACK_OPTIONS = [
        ("Original language only", "original"),
        ("Original and chosen languages", "languages"),
        ("Every language available", "all"),
    ]
    AUDIO_TRACK_MODES = [code for _, code in AUDIO_TRACK_OPTIONS]
    # yt-dlp's --audio-format names; "best" keeps the site's own audio without converting it.
    AUDIO_OPTIONS = [
        ("MP3 (plays everywhere)", "mp3"),
        ("M4A (AAC)", "m4a"),
        ("Opus", "opus"),
        ("OGG (Vorbis)", "vorbis"),
        ("FLAC (lossless)", "flac"),
        ("WAV (lossless, uncompressed)", "wav"),
        ("Original (no conversion)", "best"),
    ]
    AUDIO_FORMATS = [code for _, code in AUDIO_OPTIONS]
    # Formats where a bitrate means nothing: lossless ones, and the site's own stream.
    LOSSLESS_AUDIO = ("flac", "wav", "best")
    # The extension each --audio-format produces.
    AUDIO_EXTENSIONS = {"mp3": "mp3", "m4a": "m4a", "opus": "opus", "vorbis": "ogg", "flac": "flac", "wav": "wav"}
    # Bitrates in kbps for the lossy formats. Sites stream about 128-256 kbps, so a higher bitrate
    # keeps everything the source has but can't add detail.
    AUDIO_QUALITY_OPTIONS = [
        ("320 kbps (highest)", 320),
        ("256 kbps", 256),
        ("192 kbps", 192),
        ("160 kbps", 160),
        ("128 kbps", 128),
        ("96 kbps", 96),
        ("64 kbps (smallest)", 64),
    ]
    AUDIO_QUALITIES = [kbps for _, kbps in AUDIO_QUALITY_OPTIONS]
    DEFAULT_AUDIO_QUALITY = 320
    COVER_OPTIONS = [
        ("Square (like an album cover)", "square"),
        ("Original shape", "original"),
    ]
    COVER_SHAPES = [code for _, code in COVER_OPTIONS]
    SUBTITLE_OPTIONS = [
        ("No subtitles", "none"),
        ("Embed in the video", "embed"),
        ("Separate files", "sidecar"),
        ("Embed and keep files", "both"),
    ]
    SUBTITLE_MODES = [code for _, code in SUBTITLE_OPTIONS]
    SUBTITLE_FORMAT_OPTIONS = [
        ("SRT (most players)", "srt"),
        ("WebVTT", "vtt"),
    ]
    SUBTITLE_FORMATS = [code for _, code in SUBTITLE_FORMAT_OPTIONS]
    SPONSORBLOCK_OPTIONS = [
        ("Off", "off"),
        ("Mark segments as chapters", "mark"),
        ("Cut segments out", "remove"),
    ]
    SPONSORBLOCK_MODES = [code for _, code in SPONSORBLOCK_OPTIONS]
    SPONSORBLOCK_CATEGORIES = [
        ("Sponsor", "sponsor"),
        ("Self promotion", "selfpromo"),
        ("Interaction reminder", "interaction"),
        ("Intro", "intro"),
        ("Outro", "outro"),
        ("Preview or recap", "preview"),
        ("Filler", "filler"),
        ("Non-music section", "music_offtopic"),
    ]


class PresetDefaults:
    """The download presets offered next to the link box; users can save their own."""

    DEFAULT = "video-best-mp4"
    BUILT_IN: list[dict[str, Any]] = [
        # The highest resolution offered: "balanced" puts resolution first, so 1440p and 4K come as
        # VP9 or AV1 (which MP4 holds), and takes H.264 with AAC sound whenever it offers the same.
        {"id": "video-best-mp4", "label": "Video, best quality MP4", "kind": "video", "max_height": 0,
         "container": "mp4", "codec_profile": "balanced"},
        {"id": "video-best", "label": "Video, best quality MKV", "kind": "video", "max_height": 0,
         "container": "mkv", "codec_profile": "best"},
        {"id": "audio-mp3", "label": "Audio, MP3 320 kbps", "kind": "audio", "audio_format": "mp3",
         "audio_quality": 320},
        {"id": "audio-m4a", "label": "Audio, M4A 256 kbps", "kind": "audio", "audio_format": "m4a",
         "audio_quality": 256},
        {"id": "audio-flac", "label": "Audio, FLAC lossless", "kind": "audio", "audio_format": "flac"},
    ]
    IDS = [preset["id"] for preset in BUILT_IN]


class DownloadDefaults:
    """Queue, speed, and retry defaults; 0 means Automatic where a knob offers it."""

    # Automatic concurrency: three downloads at once overall, and never more than this per site.
    AUTO_CONCURRENT = 3
    MAX_CONCURRENT = 8
    # Automatic fragments: eight was the fastest on the original script's measurements, and the optimizer
    # measures the user's own connection (Preferences > Downloads).
    AUTO_FRAGMENTS = 8
    MAX_FRAGMENTS = 16
    RETRY_DELAY = 10
    MAX_RETRY_DELAY = 300
    # The folder under Videos (and under Music for audio) that downloads go to by default.
    FOLDER_NAME = "gfgRoyal Media Downloader"
    # The original script's default folder; adopted when it already exists so its archives keep working.
    LEGACY_FOLDER_NAME = "youtube-video-downloader"
    FILENAME_OPTIONS = [
        ("Title (quality)", "title-quality"),
        ("Title", "title"),
        ("Upload date - Title", "date-title"),
        ("Playlist number - Title", "index-title"),
    ]
    FILENAME_STYLES = [code for _, code in FILENAME_OPTIONS]
    CONCURRENT_OPTIONS = [("Automatic (3)", 0)] + [(str(count), count) for count in range(1, MAX_CONCURRENT + 1)]
    FRAGMENT_OPTIONS = [("Automatic (8)", 0)] + [(str(count), count) for count in (1, 2, 4, 6, 8, 12, 16)]


class ScheduleDefaults:
    """What happens when the queue finishes, and how often subscriptions are checked."""

    WHEN_DONE_OPTIONS = [
        ("Do nothing", "nothing"),
        ("Quit the app", "quit"),
        ("Sleep", "sleep"),
        ("Hibernate", "hibernate"),
        ("Shut down", "shutdown"),
    ]
    WHEN_DONE = [code for _, code in WHEN_DONE_OPTIONS]
    INTERVAL_OPTIONS = [
        ("Every hour", 1),
        ("Every 3 hours", 3),
        ("Every 6 hours", 6),
        ("Every 12 hours", 12),
        ("Once a day", 24),
    ]
    INTERVALS = [hours for _, hours in INTERVAL_OPTIONS]
    DEFAULT_INTERVAL_HOURS = 6


class ToolDefaults:
    """Where yt-dlp, FFmpeg, and Deno come from, and which yt-dlp releases to follow."""

    SOURCE_OPTIONS = [
        ("Managed by the app (recommended)", "managed"),
        ("Programs on PATH", "path"),
        ("Custom locations", "custom"),
    ]
    SOURCES = [code for _, code in SOURCE_OPTIONS]
    CHANNEL_OPTIONS = [
        ("Stable releases", "stable"),
        ("Nightly builds (fixes arrive sooner)", "nightly"),
    ]
    CHANNELS = [code for _, code in CHANNEL_OPTIONS]


def get_default_settings() -> Dict[str, Any]:
    """Return the complete default settings dictionary."""
    return {
        "theme": ThemeDefaults.DEFAULT_THEME,
        "downloads": {
            # "" uses Videos\gfgRoyal Media Downloader (or the original script's folder when it exists).
            "folder": "",
            # "" uses Music\gfgRoyal Media Downloader for audio downloads.
            "audio_folder": "",
            "preset": PresetDefaults.DEFAULT,
            "concurrent": 0,
            "fragments": 0,
            # 0 keeps retrying temporary failures until the download finishes or is stopped.
            "max_attempts": 0,
            "retry_delay": DownloadDefaults.RETRY_DELAY,
            "filename_style": "title-quality",
            "keep_awake": True,
        },
        "formats": {
            "container": "mp4",
            "codec_profile": "compatible",
            "audio_tracks": "original",
            "audio_langs": [],
            "audio_format": "mp3",
            "audio_quality": FormatDefaults.DEFAULT_AUDIO_QUALITY,
            "cover": "square",
            "subtitles": "none",
            "subtitle_format": "srt",
            "subtitle_langs": "en.*",
            "auto_subtitles": False,
            # Audio downloads save timed lyrics (.lrc) from the site's captions, else from LRCLIB.
            "lyrics": True,
            "lyrics_online": True,
            "embed_thumbnail": True,
            "embed_metadata": True,
            "embed_chapters": True,
            "sponsorblock": "off",
            "sponsorblock_categories": ["sponsor", "selfpromo", "interaction"],
        },
        "network": {
            # The total download speed limit in KiB/s across every download; 0 means no limit.
            "limit_kib": 0,
            # Time-of-day limits: [{"start": "09:00", "end": "18:00", "limit_kib": 500}].
            "limit_windows": [],
            "proxy": "",
            "force_ipv4": False,
        },
        "schedule": {
            # "HH:MM" to hold the queue until that time each day it is set; "" starts at once.
            "queue_start": "",
            "when_done": "nothing",
        },
        "subscriptions": {
            "interval_hours": ScheduleDefaults.DEFAULT_INTERVAL_HOURS,
            "auto_download": True,
        },
        "tools": {
            "source": "managed",
            "channel": "stable",
            "auto_update": True,
            "ytdlp_path": "",
            "ffmpeg_path": "",
            "deno_path": "",
        },
        "presets": [],
        "player": {
            "volume": 0.8,
            "muted": False,
            "speed": 1.0,
            "repeat": "off",
            "shuffle": False,
            "video_width": 960,
            "video_height": 540,
        },
        "clipboard": {"watch": False},
        "notifications": {"enabled": True},
        "tray": {
            "close_to_tray": True,
            "start_minimized": False,
        },
        "startup": {"start_with_windows": False},
        "advanced": {
            "enable_logs": LoggingDefaults.ENABLE_LOGS,
            "log_level": LoggingDefaults.DEFAULT_LOG_LEVEL,
        },
        "updates": {
            "auto_check": UpdateDefaults.AUTO_CHECK,
            "auto_install": UpdateDefaults.AUTO_INSTALL,
        },
    }
