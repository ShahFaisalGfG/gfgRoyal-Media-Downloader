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
    APP_VERSION = "1.2.0"
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
    """Default update preferences: check once a day, and install in the background, but not over a
    metered connection (mobile data, a hotspot, or one Windows was told to treat as limited)."""

    AUTO_CHECK = True
    AUTO_INSTALL = True
    ALLOW_METERED = False


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
        ("MKV (keeps everything)", "mkv"),
        ("WebM (for web browsers)", "webm"),
    ]
    CONTAINERS = [code for _, code in CONTAINER_OPTIONS]
    # Balanced is the original script's order: resolution first, then HLS and H.264/AAC at that
    # resolution, so 1440p and 4K come as VP9 or AV1 (which MP4 holds). It is the default.
    CODEC_OPTIONS = [
        ("Plays everywhere (older devices too)", "compatible"),
        ("Balanced (highest resolution first)", "balanced"),
        ("Best quality (not for older devices)", "best"),
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
        ("M4A (Apple devices)", "m4a"),
        ("Opus", "opus"),
        ("OGG", "vorbis"),
        ("FLAC (full quality, larger files)", "flac"),
        ("WAV (full quality, very large files)", "wav"),
        ("Original (as the site sends it)", "best"),
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
        ("Inside the video", "embed"),
        ("Separate files", "sidecar"),
        ("Inside the video and as files", "both"),
    ]
    SUBTITLE_MODES = [code for _, code in SUBTITLE_OPTIONS]
    # Where chosen subtitles go (Download options' and Preferences' Advanced part).
    SUBTITLE_PLACEMENT_OPTIONS = [
        ("Inside the video", "embed"),
        ("As separate files", "sidecar"),
        ("Inside the video and as files", "both"),
    ]
    # The subtitle languages offered where no video's own list is known (playlists, several links,
    # Preferences); a video read alone lists the subtitles it has instead.
    COMMON_SUBTITLE_LANGUAGES = [
        "en", "ar", "bn", "zh-Hans", "zh-Hant", "nl", "fr", "de", "el", "he", "hi", "id", "it", "ja", "ko",
        "ms", "fa", "pl", "pt", "pa", "ro", "ru", "es", "sv", "ta", "te", "th", "tr", "uk", "ur", "vi",
    ]
    SUBTITLE_FORMAT_OPTIONS = [
        ("SRT (most players)", "srt"),
        ("VTT (web players)", "vtt"),
    ]
    SUBTITLE_FORMATS = [code for _, code in SUBTITLE_FORMAT_OPTIONS]
    SPONSORBLOCK_OPTIONS = [
        ("Off", "off"),
        ("Mark sponsor parts as chapters", "mark"),
        ("Cut sponsor parts out", "remove"),
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
    # The Video | Audio switch beside the link box: which of the Smart Mode defaults a download uses.
    KIND_OPTIONS = [
        ("Video", "video"),
        ("Audio", "audio"),
    ]
    KINDS = [code for _, code in KIND_OPTIONS]
    # A link to one video inside a playlist ("watch?v=...&list=..."): ask, or the remembered answer.
    PLAYLIST_LINK_OPTIONS = [
        ("Ask each time", "ask"),
        ("Download just the video", "video"),
        ("Download the whole playlist", "playlist"),
    ]
    PLAYLIST_LINKS = [code for _, code in PLAYLIST_LINK_OPTIONS]
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
    """Where the download tools (yt-dlp, FFmpeg, Deno, gallery-dl, spotDL) come from, and which yt-dlp
    releases to follow."""

    SOURCE_OPTIONS = [
        ("Kept up to date by the app (recommended)", "managed"),
        ("Programs already installed on this PC", "path"),
        ("Programs I choose", "custom"),
    ]
    SOURCES = [code for _, code in SOURCE_OPTIONS]
    CHANNEL_OPTIONS = [
        ("Stable (recommended)", "stable"),
        ("Early fixes (updated daily, less tested)", "nightly"),
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
            # "" uses Pictures\gfgRoyal Media Downloader for pictures from posts.
            "photo_folder": "",
            # A post's pictures are saved along with its videos (gallery-dl), and picture-only posts too.
            "save_photos": True,
            # Smart Mode: Download downloads at once with the Video or Audio defaults below ("formats");
            # off, it opens Download options first. "kind" is the Video | Audio switch's choice.
            "smart_mode": True,
            "kind": "video",
            # A video inside a playlist: "ask", or the remembered "video" or "playlist".
            "playlist_links": "ask",
            # Download options' "Record from the start" for a live stream it has read (a download that
            # doesn't know the link is live records from the moment it starts).
            "live_from_start": True,
            "concurrent": 0,
            "fragments": 0,
            # 0 keeps retrying temporary failures until the download finishes or is stopped.
            "max_attempts": 0,
            "retry_delay": DownloadDefaults.RETRY_DELAY,
            "filename_style": "title-quality",
            "keep_awake": True,
            # Finished and cancelled downloads leave the Downloads list when the app closes; the
            # Library keeps their files, and failed or unfinished downloads stay to be resumed.
            "clear_finished_on_exit": True,
        },
        "formats": {
            # The Smart Mode defaults and Download options' starting choices. Video:
            "max_height": 0,
            "container": "mp4",
            "codec_profile": "balanced",
            "audio_tracks": "original",
            "audio_langs": [],
            "audio_format": "mp3",
            "audio_quality": FormatDefaults.DEFAULT_AUDIO_QUALITY,
            "cover": "square",
            # "none" downloads no subtitles by default; otherwise where they go. The languages are
            # yt-dlp patterns ("en.*" is every kind of English), and the placement is kept for when
            # languages are chosen again.
            "subtitles": "none",
            "subtitle_placement": "embed",
            "subtitle_format": "srt",
            "subtitle_langs": "en.*",
            "auto_subtitles": False,
            # Audio downloads save timed lyrics (.lrc) from the site's captions, else from LRCLIB.
            "lyrics": True,
            "lyrics_online": True,
            "embed_thumbnail": True,
            "embed_metadata": True,
            "embed_chapters": True,
            # Audio's own "Save in the file" choices (the cover, the details, the chapters).
            "audio_embed_cover": True,
            "audio_embed_metadata": True,
            "audio_embed_chapters": True,
            # One file per chapter of a video that has chapters, for videos and for songs (an album).
            "split_chapters": False,
            "audio_split_chapters": False,
            # A part of a video is cut at the exact times (re-encoding it) instead of at keyframes.
            "exact_cut": False,
            # SponsorBlock applies to video and audio alike.
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
            "gallery_dl_path": "",
            "spotdl_path": "",
        },
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
            # The first close to the tray says the app is still running there; said once.
            "told_running": False,
        },
        "startup": {"start_with_windows": False},
        "advanced": {
            "enable_logs": LoggingDefaults.ENABLE_LOGS,
            "log_level": LoggingDefaults.DEFAULT_LOG_LEVEL,
        },
        "updates": {
            "auto_check": UpdateDefaults.AUTO_CHECK,
            "auto_install": UpdateDefaults.AUTO_INSTALL,
            "allow_metered": UpdateDefaults.ALLOW_METERED,
        },
        # The installer's connection choices as this user's settings last applied them
        # ("OnlineLyrics=0;ToolUpdates=1;UpdateChecks=1"); see utils/install_choices.py.
        "install": {"connections": ""},
    }
