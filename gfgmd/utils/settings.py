# settings.py - settings file load, save, and merge utilities

import copy
import json
import os
import re
import threading
from collections.abc import Callable
from typing import Any, Dict

from gfgmd.config.defaults import (
    DownloadDefaults,
    FormatDefaults,
    LoggingDefaults,
    ScheduleDefaults,
    ThemeDefaults,
    ToolDefaults,
)
from gfgmd.config.defaults import get_default_settings as _get_defaults
from gfgmd.utils.console import safe_print
from gfgmd.utils.paths import data_dir


def get_settings_file() -> str:
    """The path to settings.json: in the app's data folder, or next to this module from source."""
    folder = data_dir()
    if folder:
        return os.path.join(folder, "settings.json")
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(utils_dir, "settings.json")


def get_default_settings() -> Dict[str, Any]:
    """The complete default settings dictionary."""
    return _get_defaults()


# Parsed settings keyed by the file's (path, mtime, size). A file that can't be parsed is cached as
# the defaults too, so it is read (and reported) once until it changes.
_cache_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], Dict[str, Any]] | None = None
_read_error = False


def load_settings() -> Dict[str, Any]:
    """Load settings.json, merging with defaults for any missing or invalid keys.

    Returns a fresh copy each time; the parsed file is reused until it changes on disk.
    """
    global _cache, _read_error
    path = get_settings_file()
    try:
        stat = os.stat(path)
    except OSError:
        return get_default_settings()
    key = (path, stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if _cache is not None and _cache[0] == key:
            return copy.deepcopy(_cache[1])
    damaged = False
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)
        defaults = get_default_settings()
        settings = merge_settings(defaults, drop_invalid(migrate(raw), defaults))
    except OSError as error:
        safe_print(f"settings.json could not be opened ({error}); using the defaults")
        return get_default_settings()
    except (ValueError, TypeError) as error:
        safe_print(f"settings.json could not be read ({error}); using the defaults")
        settings, damaged = get_default_settings(), True
    with _cache_lock:
        _cache = (key, settings)
        _read_error = _read_error or damaged
    return copy.deepcopy(settings)


def take_read_error() -> bool:
    """True once after settings.json was found damaged (so the defaults are in use), then False."""
    global _read_error
    with _cache_lock:
        damaged, _read_error = _read_error, False
    return damaged


def save_settings(settings: Dict[str, Any]) -> bool:
    """Persist settings to settings.json atomically. Returns True on success.

    Writes a temp file next to it, forces it to disk, and swaps it in, so neither a crash nor a
    power cut mid-write can leave a truncated settings.json behind.
    """
    global _cache
    path = get_settings_file()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except (OSError, TypeError, ValueError) as error:
        safe_print(f"settings.json could not be saved ({error})")
        _discard(tmp_path)
        return False
    with _cache_lock:
        _cache = None
    return True


def _discard(path: str) -> None:
    """Delete a temp file that will not be used, ignoring one that was never created."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        safe_print(f"{path} could not be removed ({error})")


_CLOCK = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_SPONSOR_CODES = {code for _, code in FormatDefaults.SPONSORBLOCK_CATEGORIES}


def is_clock(value: Any) -> bool:
    """True for a 24-hour "HH:MM" time."""
    return isinstance(value, str) and _CLOCK.fullmatch(value) is not None


def _limit_window(window: Any) -> bool:
    """A time-of-day speed limit: {"start": "HH:MM", "end": "HH:MM", "limit_kib": int > 0}."""
    return (isinstance(window, dict) and set(window) == {"start", "end", "limit_kib"}
            and is_clock(window["start"]) and is_clock(window["end"]) and window["start"] != window["end"]
            and isinstance(window["limit_kib"], int) and not isinstance(window["limit_kib"], bool)
            and window["limit_kib"] > 0)


# 1.0.0's built-in download presets, which Smart mode replaced; migrate() carries the one that was the
# Download button's into the Video or Audio defaults.
_OLD_PRESETS: Dict[str, Dict[str, Any]] = {
    "video-best-mp4": {"kind": "video", "max_height": 0, "container": "mp4", "codec_profile": "balanced"},
    "video-best": {"kind": "video", "max_height": 0, "container": "mkv", "codec_profile": "best"},
    "audio-mp3": {"kind": "audio", "audio_format": "mp3", "audio_quality": 320},
    "audio-m4a": {"kind": "audio", "audio_format": "m4a", "audio_quality": 256},
    "audio-flac": {"kind": "audio", "audio_format": "flac"},
}
_PRESET_FORMATS = ("max_height", "container", "codec_profile", "audio_tracks", "audio_langs", "audio_format",
                   "audio_quality", "cover", "subtitles", "subtitle_format", "sponsorblock", "lyrics")
_AUDIO_EMBEDS = (("embed_thumbnail", "audio_embed_cover"), ("embed_metadata", "audio_embed_metadata"),
                 ("embed_chapters", "audio_embed_chapters"))


def migrate(raw: Any) -> Any:
    """Carry an older settings file over to today's keys (in place), before its values are checked.

    1.0.0's download presets became Smart mode: the preset the Download button used becomes the
    Video or Audio defaults and the switch's choice, so Download keeps doing what it did. Audio got
    its own "Save in the file" choices, which start as the shared ones were, and subtitles a
    placement kept apart from whether they download.
    """
    if not isinstance(raw, dict):
        return raw
    downloads, formats = raw.get("downloads"), raw.setdefault("formats", {})
    if not isinstance(formats, dict):
        return raw
    if isinstance(downloads, dict) and "kind" not in downloads and isinstance(downloads.get("preset"), str):
        saved = {preset.get("id"): preset for preset in raw.get("presets", []) if isinstance(preset, dict)}
        preset = saved.get(downloads["preset"]) or _OLD_PRESETS.get(downloads["preset"]) or _OLD_PRESETS["video-best-mp4"]
        downloads["kind"] = "audio" if preset.get("kind") == "audio" else "video"
        formats.update({key: preset[key] for key in _PRESET_FORMATS if key in preset})
    for shared, audio in _AUDIO_EMBEDS:
        if audio not in formats and shared in formats:
            formats[audio] = formats[shared]
    if "subtitle_placement" not in formats and formats.get("subtitles") in ("embed", "sidecar", "both"):
        formats["subtitle_placement"] = formats["subtitles"]
    return raw


def _int_range(low: int, high: int) -> Callable[[Any], bool]:
    return lambda value: low <= value <= high


def _audio_langs(value: Any) -> bool:
    """Up to 12 audio language codes such as "es" or "pt-BR"."""
    return (isinstance(value, list) and len(value) <= 12
            and all(isinstance(code, str) and re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,2}", code)
                    for code in value))


# The values each setting may hold, by leaf key name; a key not listed accepts any value of its type.
_ALLOWED: Dict[str, Callable[[Any], bool]] = {
    "theme": lambda value: value in ThemeDefaults.SUPPORTED_THEMES,
    "log_level": lambda value: value in LoggingDefaults.SUPPORTED_LOG_LEVELS,
    "kind": lambda value: value in DownloadDefaults.KINDS,
    "playlist_links": lambda value: value in DownloadDefaults.PLAYLIST_LINKS,
    "max_height": lambda value: value in FormatDefaults.HEIGHTS,
    "container": lambda value: value in FormatDefaults.CONTAINERS,
    "codec_profile": lambda value: value in FormatDefaults.CODEC_PROFILES,
    "audio_format": lambda value: value in FormatDefaults.AUDIO_FORMATS,
    "audio_quality": lambda value: value in FormatDefaults.AUDIO_QUALITIES,
    "audio_tracks": lambda value: value in FormatDefaults.AUDIO_TRACK_MODES,
    "audio_langs": _audio_langs,
    "cover": lambda value: value in FormatDefaults.COVER_SHAPES,
    "subtitles": lambda value: value in FormatDefaults.SUBTITLE_MODES,
    "subtitle_format": lambda value: value in FormatDefaults.SUBTITLE_FORMATS,
    "subtitle_langs": lambda value: re.fullmatch(r"[A-Za-z0-9_.*,-]{1,2000}", value) is not None,
    "subtitle_placement": lambda value: value in FormatDefaults.SUBTITLE_MODES and value != "none",
    "sponsorblock": lambda value: value in FormatDefaults.SPONSORBLOCK_MODES,
    "sponsorblock_categories": lambda value: all(code in _SPONSOR_CODES for code in value),
    "filename_style": lambda value: value in DownloadDefaults.FILENAME_STYLES,
    "concurrent": _int_range(0, DownloadDefaults.MAX_CONCURRENT),
    "fragments": _int_range(0, DownloadDefaults.MAX_FRAGMENTS),
    "max_attempts": _int_range(0, 1000),
    "retry_delay": _int_range(1, 3600),
    "limit_kib": _int_range(0, 10 * 1024 * 1024),
    "limit_windows": lambda value: len(value) <= 12 and all(_limit_window(window) for window in value),
    "queue_start": lambda value: value == "" or is_clock(value),
    "when_done": lambda value: value in ScheduleDefaults.WHEN_DONE,
    "interval_hours": lambda value: value in ScheduleDefaults.INTERVALS,
    "source": lambda value: value in ToolDefaults.SOURCES,
    "channel": lambda value: value in ToolDefaults.CHANNELS,
    "volume": lambda value: 0 <= value <= 1,
    "speed": lambda value: 0.25 <= value <= 2,
    "repeat": lambda value: value in ("off", "all", "one"),
    "video_width": _int_range(320, 16384),
    "video_height": _int_range(180, 16384),
}


def drop_invalid(settings: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Return `settings` without the keys the defaults no longer define or whose values can't be used.

    A value of the wrong type (a hand-edited string where a number belongs) or outside its choices
    (a theme of "purple") is dropped, so the default applies instead of breaking the app later.
    """
    if not isinstance(settings, dict):
        raise TypeError("settings must be a JSON object")
    result: Dict[str, Any] = {}
    for key, value in settings.items():
        if key not in defaults:
            continue
        if isinstance(defaults[key], dict):
            if isinstance(value, dict):
                result[key] = drop_invalid(value, defaults[key])
        elif _same_type(value, defaults[key]) and _ALLOWED.get(key, _any_value)(value):
            result[key] = value
    return result


def _any_value(_value: Any) -> bool:
    """The check for settings that accept any value of their type."""
    return True


def _same_type(value: Any, default: Any) -> bool:
    """True when value can stand in for default; bool and int are told apart."""
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(value, bool) and isinstance(default, bool)
    return isinstance(value, type(default))


def merge_settings(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge overrides onto defaults, recursively preserving nested structure."""
    result = defaults.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_settings(result[key], value)
        else:
            result[key] = value
    return result
