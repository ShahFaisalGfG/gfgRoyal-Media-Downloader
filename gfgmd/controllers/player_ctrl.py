# player_ctrl.py - the built-in players: what plays, in what order, and what goes with it
#
# Qt Multimedia does the playing in QML (the video window's and the audio bar's MediaPlayer, with
# the FFmpeg backend PySide6 ships, which decodes on the GPU when it can). This controller decides
# what they play: a video in the player window, or a list of audio files in the bar, with shuffle and
# repeat. It finds what goes with each file (subtitle and lyric files beside it, its cover, its title
# and artist from the library), remembers where playback stopped, and keeps volume, speed, and the
# video window's size in the preferences.

from __future__ import annotations

import hashlib
import os
import random
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QLocale, QObject, QUrl, Signal, Slot

from gfgmd.core.captions import COVER_EXTENSIONS, Cue, cue_at, line_at, parse_file, sidecars
from gfgmd.core.naming import AUDIO_EXTENSIONS
from gfgmd.core.platform import hidden_window_flags
from gfgmd.core.tools import ToolsMissing
from gfgmd.models.list_model import DictListModel
from gfgmd.services.context import AppContext
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.settings import load_settings, save_settings
from gfgmd.utils.logging import write_log

QUEUE_ROLES = ("key", "path", "title", "artist", "current")
REPEAT_MODES = ("off", "all", "one")
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
# Positions this close to either end aren't worth resuming from.
RESUME_MARGIN = 10.0


def is_audio(path: str) -> bool:
    """True for files the audio bar plays (by extension)."""
    return Path(path).suffix.lower().lstrip(".") in AUDIO_EXTENSIONS


def file_url(path: str) -> str:
    """A file:// URL QML can load."""
    return QUrl.fromLocalFile(path).toString() if path else ""


class PlayerController(QObject):
    """The video window's and the audio bar's playlists, sidecars, covers, and preferences."""

    videoChanged = Signal()
    audioChanged = Signal()
    lyricsChanged = Signal()
    coverChanged = Signal()
    prefsChanged = Signal()
    # QML shows the video window, or starts the audio bar's player.
    videoRequested = Signal()
    audioRequested = Signal()
    # The tray's Play/Pause.
    togglePlayRequested = Signal()
    notice = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._runner = TaskRunner(1, self)
        self._video = ""
        self._video_list: list[str] = []
        self._video_cues: list[Cue] = []
        self._video_captions: list[Path] = []
        self._caption_index = -1
        self._queue = DictListModel(QUEUE_ROLES, "key", self)
        self._audio_paths: list[str] = []
        self._order: list[int] = []
        self._position = -1  # index into self._order
        self._lyrics: list[Cue] = []
        self._cover = ""
        self._audio_playing = False

    # ── Shared ────────────────────────────────────────────────────────────

    @Slot(str)
    def play(self, path: str) -> None:
        """Play one downloaded file: audio in the bar, video in the player window."""
        self.playFrom(path, [])

    @Slot(str, list)
    def playFrom(self, path: str, playlist: list[str]) -> None:
        """Play `path`; the files of its kind in `playlist` (a library view) become Previous and Next."""
        if not path or not os.path.isfile(path):
            self.notice.emit("The file isn't there any more; it may have been moved or deleted.")
            return
        listed = [str(entry) for entry in playlist]
        if path not in listed:
            listed.insert(0, path)
        if is_audio(path):
            songs = [entry for entry in listed if is_audio(entry)]
            self.playAudio(songs, songs.index(path))
        else:
            self.playVideo(path, [entry for entry in listed if not is_audio(entry)])

    @Slot(str, result=bool)
    def isAudio(self, path: str) -> bool:
        """True when the audio bar (not the video window) plays this file."""
        return is_audio(path)

    @Slot(str, result=float)
    def resumeAt(self, path: str) -> float:
        """Where to start a file, in milliseconds: where it stopped last time, unless near either end."""
        return self._context.store.position_for(path) * 1000.0

    @Slot(str, float, float)
    def savePosition(self, path: str, position_ms: float, duration_ms: float) -> None:
        """Remember where playback stopped; a file stopped near its end is forgotten, to start over next time."""
        if not path:
            return
        position, duration = position_ms / 1000.0, duration_ms / 1000.0
        if position < RESUME_MARGIN or (duration > 0 and duration - position < RESUME_MARGIN):
            self._context.store.clear_position(path)
        else:
            self._context.store.save_position(path, position, duration)

    @Slot(str, int, int, result=str)
    def trackLabel(self, title: str, language: int, number: int) -> str:
        """A readable name for an audio or subtitle track: its title, else its language, else "Track n"."""
        if title:
            return title
        if language > 0:
            name = QLocale.languageToString(QLocale.Language(language))
            if name and name != "C":
                return name
        return f"Track {number}"

    @Slot(str)
    def openInSystem(self, path: str) -> None:
        """Open a file in the program Windows uses for it (when the built-in player can't play it)."""
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows only
        except (AttributeError, OSError) as error:
            self.notice.emit(f"Couldn't open the file: {error}")

    # ── Preferences ───────────────────────────────────────────────────────

    def _pref(self, key: str, default: Any) -> Any:
        return load_settings().get("player", {}).get(key, default)

    def _save_pref(self, key: str, value: Any) -> None:
        settings = load_settings()
        settings.setdefault("player", {})[key] = value
        try:
            save_settings(settings)
        except OSError as error:
            write_log(f"Saving the player preferences failed: {error}", "critical")
        self.prefsChanged.emit()

    @Property(float, notify=prefsChanged)
    def volume(self) -> float:
        return float(self._pref("volume", 0.8))

    @Slot(float)
    def setVolume(self, volume: float) -> None:
        self._save_pref("volume", round(min(max(volume, 0.0), 1.0), 3))

    @Property(bool, notify=prefsChanged)
    def muted(self) -> bool:
        return bool(self._pref("muted", False))

    @Slot(bool)
    def setMuted(self, muted: bool) -> None:
        self._save_pref("muted", muted)

    @Property(float, notify=prefsChanged)
    def speed(self) -> float:
        return float(self._pref("speed", 1.0))

    @Slot(float)
    def setSpeed(self, speed: float) -> None:
        self._save_pref("speed", min(SPEEDS, key=lambda option: abs(option - speed)))

    @Property(list, constant=True)
    def speeds(self) -> list[float]:
        return list(SPEEDS)

    @Property(str, notify=prefsChanged)
    def repeat(self) -> str:
        mode = str(self._pref("repeat", "off"))
        return mode if mode in REPEAT_MODES else "off"

    @Slot()
    def cycleRepeat(self) -> None:
        """Off, then repeat the list, then repeat one song."""
        self._save_pref("repeat", REPEAT_MODES[(REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)])

    @Property(bool, notify=prefsChanged)
    def shuffle(self) -> bool:
        return bool(self._pref("shuffle", False))

    @Slot(bool)
    def setShuffle(self, shuffle: bool) -> None:
        self._save_pref("shuffle", shuffle)
        current = self._order[self._position] if 0 <= self._position < len(self._order) else 0
        self._make_order(current)
        self._sync_queue()

    @Property(int, notify=prefsChanged)
    def videoWidth(self) -> int:
        return int(self._pref("video_width", 960))

    @Property(int, notify=prefsChanged)
    def videoHeight(self) -> int:
        return int(self._pref("video_height", 540))

    @Slot(int, int)
    def saveVideoSize(self, width: int, height: int) -> None:
        """Remember the video window's size for next time."""
        settings = load_settings()
        player = settings.setdefault("player", {})
        player["video_width"], player["video_height"] = max(width, 320), max(height, 180)
        try:
            save_settings(settings)
        except OSError as error:
            write_log(f"Saving the player window size failed: {error}", "critical")

    # ── Video ─────────────────────────────────────────────────────────────

    @Slot(str, list)
    def playVideo(self, path: str, playlist: list[str]) -> None:
        """Open a video in the player window; `playlist` (videos in order) enables Previous and Next."""
        self._video = path
        self._video_list = [str(entry) for entry in playlist if not is_audio(str(entry))] or [path]
        self._video_captions = [entry for entry in sidecars(Path(path)) if entry.suffix.lower() != ".lrc"]
        self._caption_index = -1
        self._video_cues = []
        self.videoChanged.emit()
        self.videoRequested.emit()

    @Property(str, notify=videoChanged)
    def videoPath(self) -> str:
        return self._video

    @Property(str, notify=videoChanged)
    def videoUrl(self) -> str:
        return file_url(self._video)

    @Property(str, notify=videoChanged)
    def videoTitle(self) -> str:
        return self._title_of(self._video)

    @Property(bool, notify=videoChanged)
    def hasPreviousVideo(self) -> bool:
        return self._video in self._video_list and self._video_list.index(self._video) > 0

    @Property(bool, notify=videoChanged)
    def hasNextVideo(self) -> bool:
        return self._video in self._video_list and self._video_list.index(self._video) < len(self._video_list) - 1

    @Slot(int)
    def stepVideo(self, step: int) -> None:
        """The previous (-1) or next (+1) video of the list."""
        if self._video not in self._video_list:
            return
        index = self._video_list.index(self._video) + step
        if 0 <= index < len(self._video_list):
            self.playVideo(self._video_list[index], self._video_list)

    @Property(list, notify=videoChanged)
    def captionFiles(self) -> list[str]:
        """Names of the subtitle files saved beside the video ("English (en.srt)")."""
        stem = Path(self._video).stem
        return [entry.name[len(stem):].lstrip(".") or entry.name for entry in self._video_captions]

    @Property(int, notify=videoChanged)
    def captionFile(self) -> int:
        return self._caption_index

    @Slot(int)
    def setCaptionFile(self, index: int) -> None:
        """Show a subtitle file from beside the video (-1 for none)."""
        if 0 <= index < len(self._video_captions):
            self._caption_index = index
            self._video_cues = parse_file(self._video_captions[index])
        else:
            self._caption_index, self._video_cues = -1, []
        self.videoChanged.emit()

    @Slot(float, result=str)
    def captionAt(self, position_ms: float) -> str:
        """The subtitle file's line at this moment ("" between lines)."""
        index = cue_at(self._video_cues, position_ms / 1000.0)
        return self._video_cues[index].text if index >= 0 else ""

    # ── Audio ─────────────────────────────────────────────────────────────

    @Slot(list, int)
    def playAudio(self, paths: list[str], start: int) -> None:
        """Play audio files in the bar, starting at index `start`."""
        self._audio_paths = [str(path) for path in paths if is_audio(str(path))]
        if not self._audio_paths:
            return
        start = min(max(start, 0), len(self._audio_paths) - 1)
        self._make_order(start)
        self._load_current()
        self.audioRequested.emit()

    def _make_order(self, first: int) -> None:
        """The play order: as listed, or shuffled with the current song first."""
        order = list(range(len(self._audio_paths)))
        if self.shuffle and len(order) > 1:
            rest = [index for index in order if index != first]
            random.shuffle(rest)
            order = [first] + rest
            self._position = 0
        else:
            self._position = first
        self._order = order

    def _load_current(self) -> None:
        path = self._current()
        self._lyrics = []
        lyric_file = Path(path).with_suffix(".lrc") if path else None
        if lyric_file is not None and lyric_file.is_file():
            self._lyrics = parse_file(lyric_file)
        self._cover = ""
        self._sync_queue()
        self.audioChanged.emit()
        self.lyricsChanged.emit()
        self.coverChanged.emit()
        if path:
            self._runner.start(self._find_cover, path, on_done=lambda cover, p=path: self._cover_found(p, cover),
                               on_error=lambda _message: None)

    def _sync_queue(self) -> None:
        current = self._order[self._position] if 0 <= self._position < len(self._order) else -1
        rows = []
        for index in self._order:
            path = self._audio_paths[index]
            record = self._context.store.history_for_path(path) or {}
            rows.append({"key": path, "path": path, "title": record.get("title") or Path(path).stem,
                         "artist": _artist(record), "current": index == current})
        self._queue.sync(rows)

    @Property(QObject, constant=True)
    def queue(self) -> DictListModel:
        """The audio play order, with the current song marked."""
        return self._queue

    @Property(bool, notify=audioChanged)
    def hasAudio(self) -> bool:
        return 0 <= self._position < len(self._order)

    def _current(self) -> str:
        """The path of the song playing (or loaded), "" when the bar is closed."""
        if not 0 <= self._position < len(self._order):
            return ""
        return self._audio_paths[self._order[self._position]]

    @Property(str, notify=audioChanged)
    def audioPath(self) -> str:
        return self._current()

    @Property(str, notify=audioChanged)
    def audioUrl(self) -> str:
        return file_url(self._current())

    @Property(str, notify=audioChanged)
    def audioTitle(self) -> str:
        return self._title_of(self._current())

    @Property(str, notify=audioChanged)
    def audioArtist(self) -> str:
        path = self._current()
        return _artist(self._context.store.history_for_path(path) or {}) if path else ""

    @Property(str, notify=audioChanged)
    def audioThumbnail(self) -> str:
        """The online thumbnail from the library, shown while (or when) no cover is found in the file."""
        path = self._current()
        record = self._context.store.history_for_path(path) if path else None
        return str(record.get("thumbnail") or "") if record else ""

    @Property(str, notify=coverChanged)
    def audioCover(self) -> str:
        """A local cover image for the current song: from its tags, or saved beside it."""
        return file_url(self._cover)

    @Property(int, notify=audioChanged)
    def audioIndex(self) -> int:
        return self._position

    @Property(int, notify=audioChanged)
    def audioCount(self) -> int:
        return len(self._order)

    @Slot(int)
    def stepAudio(self, step: int) -> None:
        """Previous (-1) or next (+1) song; past the end it wraps when repeating the list."""
        if not self._order:
            return
        position = self._position + step
        if position >= len(self._order) or position < 0:
            if self.repeat != "all":
                return
            position %= len(self._order)
        self._position = position
        self._load_current()

    @Slot(result=bool)
    def audioEnded(self) -> bool:
        """The current song ended: True when another one (or the same, repeating) should play."""
        if not self._order:
            return False
        if self.repeat == "one":
            return True
        if self._position + 1 < len(self._order) or self.repeat == "all":
            self.stepAudio(1)
            return True
        return False

    @Slot(int)
    def jumpTo(self, row: int) -> None:
        """Play the queue's row `row`."""
        if 0 <= row < len(self._order):
            self._position = row
            self._load_current()

    @Slot()
    def stopAudio(self) -> None:
        """Close the audio bar."""
        self._audio_paths, self._order, self._position = [], [], -1
        self._lyrics, self._cover = [], ""
        self._queue.reset([])
        self.audioChanged.emit()
        self.lyricsChanged.emit()
        self.coverChanged.emit()

    @Property(bool, notify=audioChanged)
    def audioPlaying(self) -> bool:
        return self._audio_playing

    @Slot(bool)
    def setAudioPlaying(self, playing: bool) -> None:
        """The bar reports play and pause, for the tray's menu."""
        if playing != self._audio_playing:
            self._audio_playing = playing
            self.audioChanged.emit()

    @Property(list, notify=lyricsChanged)
    def lyrics(self) -> list[str]:
        """The current song's lyric lines (from "<song>.lrc")."""
        return [cue.text for cue in self._lyrics]

    @Slot(float, result=int)
    def lyricLine(self, position_ms: float) -> int:
        """The lyric line reached at this moment, or -1 before the first."""
        return line_at(self._lyrics, position_ms / 1000.0)

    @Slot(int, result=float)
    def lyricStart(self, line: int) -> float:
        """Where a lyric line starts, in milliseconds (for click to seek)."""
        return self._lyrics[line].start * 1000.0 if 0 <= line < len(self._lyrics) else 0.0

    # ── Helpers ───────────────────────────────────────────────────────────

    def _title_of(self, path: str) -> str:
        if not path:
            return ""
        record = self._context.store.history_for_path(path)
        return str(record["title"]) if record and record.get("title") else Path(path).stem

    def _find_cover(self, path: str) -> str:
        """On the pool: a cover beside the file, else the one in its tags, saved to the cover cache."""
        media = Path(path)
        for extension in COVER_EXTENSIONS:
            beside = media.with_suffix(extension)
            if beside.is_file():
                return str(beside)
        try:
            ffmpeg = self._context.tools().ffmpeg
        except ToolsMissing:
            return ""
        stat = media.stat()
        key = hashlib.sha256(f"{media}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()[:24]
        target = self._context.cache_dir / "covers" / f"{key}.jpg"
        if target.is_file():
            return str(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(media), "-map", "0:v:0", "-frames:v", "1",
                                 "-vf", "scale='min(600,iw)':-2", str(target)],
                                capture_output=True, check=False, timeout=60, creationflags=hidden_window_flags())
        return str(target) if result.returncode == 0 and target.is_file() else ""

    def _cover_found(self, path: str, cover: str) -> None:
        if path == self._current():
            self._cover = cover
            self.coverChanged.emit()

    def shutdown(self) -> None:
        self._runner.shutdown(3000)


def _artist(record: dict[str, Any]) -> str:
    """The uploader from the library, without YouTube Music's " - Topic"."""
    uploader = str(record.get("uploader") or "")
    return uploader[:-len(" - Topic")] if uploader.endswith(" - Topic") else uploader
