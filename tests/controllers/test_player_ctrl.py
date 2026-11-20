"""The players' controller: what plays next, resume positions, sidecar captions and lyrics, preferences."""

import sqlite3
import time
from pathlib import Path

import pytest

from gfgmd.controllers.player_ctrl import PlayerController, language_name
from gfgmd.core.store import SCHEMA_VERSION, Store
from gfgmd.core.tools import ToolSet
from gfgmd.services.context import AppContext
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings

TOOLS = ToolSet("FAKE-YT-DLP", "FAKE-FFMPEG", "FAKE-FFPROBE", "deno")


@pytest.fixture
def context(tmp_path: Path, monkeypatch):
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    save_settings(get_default_settings())
    yield context
    context.close()


@pytest.fixture
def player(qapp, context):
    controller = PlayerController(context)
    yield controller
    controller.shutdown()


def files(folder: Path, *names: str) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        (folder / name).write_bytes(b"media")
        paths.append(str(folder / name))
    return paths


def test_library_play_splits_audio_and_video(player, tmp_path):
    """Songs go to the audio bar with their neighbours as the queue; videos to the window with theirs."""
    song_a, clip, song_b, movie = files(tmp_path, "a.mp3", "clip.mp4", "b.m4a", "movie.mkv")
    requests = []
    player.audioRequested.connect(lambda: requests.append("audio"))
    player.videoRequested.connect(lambda: requests.append("video"))
    player.playFrom(song_b, [song_a, clip, song_b, movie])
    assert requests == ["audio"] and player.audioPath == song_b and player.audioCount == 2
    assert [player.queue.get(i)["path"] for i in range(player.queue.count)] == [song_a, song_b]
    assert player.queue.get(1)["current"] and player.audioTitle == "b"
    player.playFrom(clip, [song_a, clip, song_b, movie])
    assert requests == ["audio", "video"] and player.videoPath == clip
    assert not player.hasPreviousVideo and player.hasNextVideo
    player.stepVideo(1)
    assert player.videoPath == movie and player.hasPreviousVideo and not player.hasNextVideo


def test_missing_file_is_reported(player, tmp_path):
    notices = []
    player.notice.connect(notices.append)
    player.play(str(tmp_path / "gone.mp3"))
    assert not player.hasAudio and "isn't there" in notices[0]


def test_repeat_and_end_of_list(player, tmp_path):
    songs = files(tmp_path, "1.mp3", "2.mp3")
    player.playAudio(songs, 0)
    assert player.audioEnded() and player.audioPath == songs[1]
    assert not player.audioEnded()  # repeat off: the list ends
    player.cycleRepeat()
    assert player.repeat == "all" and player.audioEnded() and player.audioPath == songs[0]
    player.cycleRepeat()
    assert player.repeat == "one" and player.audioEnded() and player.audioPath == songs[0]
    player.cycleRepeat()
    assert player.repeat == "off" and load_settings()["player"]["repeat"] == "off"


def test_shuffle_keeps_the_current_song_first(player, tmp_path):
    songs = files(tmp_path, *[f"{n}.mp3" for n in range(8)])
    player.setShuffle(True)
    player.playAudio(songs, 5)
    order = [player.queue.get(i)["path"] for i in range(player.queue.count)]
    assert order[0] == songs[5] and sorted(order) == sorted(songs)
    player.stopAudio()
    assert not player.hasAudio and player.queue.count == 0


def test_resume_positions(player, tmp_path):
    """Positions are kept in seconds; near either end they're forgotten so the file starts over."""
    path = files(tmp_path, "talk.mp4")[0]
    player.savePosition(path, 125_000, 600_000)
    assert player.resumeAt(path) == 125_000
    player.savePosition(path, 595_000, 600_000)
    assert player.resumeAt(path) == 0
    player.savePosition(path, 3_000, 600_000)
    assert player.resumeAt(path) == 0


def test_sidecar_subtitles_and_lyrics(player, tmp_path):
    video = files(tmp_path, "Talk (1080p).mp4")[0]
    (tmp_path / "Talk (1080p).en.srt").write_text("1\n00:00:01,000 --> 00:00:02,500\nHello\n", encoding="utf-8")
    player.playVideo(video, [])
    assert player.captionFiles == ["English"] and player.captionFile == -1
    player.setCaptionFile(0)
    assert player.captionAt(1500) == "Hello" and player.captionAt(3000) == ""
    song = files(tmp_path, "Song.mp3")[0]
    (tmp_path / "Song.lrc").write_text("[00:01.00]One\n[00:05.00]Two\n", encoding="utf-8")
    player.playAudio([song], 0)
    assert player.lyrics == ["One", "Two"]
    assert [player.lyricLine(ms) for ms in (500, 2000, 6000)] == [-1, 0, 1]
    assert player.lyricStart(1) == 5000


def test_subtitle_files_are_named_by_language(player, tmp_path):
    """The subtitle menu shows language names, numbered when two files share one, never file suffixes."""
    video = files(tmp_path, "Talk.mp4")[0]
    for name in ("Talk.en.srt", "Talk.en.vtt", "Talk.en-orig.vtt", "Talk.es-419.srt", "Talk.srt", "Talk.xx.srt"):
        (tmp_path / name).write_text("", encoding="utf-8")
    player.playVideo(video, [])
    assert sorted(player.captionFiles) == sorted(["English 1", "English 2", "English (original)",
                                                  "Spanish (Latin America)", "Subtitles 1", "Subtitles 2"])


@pytest.mark.parametrize(("code", "name"), [("en", "English"), ("pt-BR", "Portuguese (Brazil)"),
                                            ("zh-Hans", "Chinese (Simplified Han)"), ("en-nP7-2PuUl7o", "English"),
                                            ("xx", ""), ("live_chat", "")])
def test_language_names(player, code, name):
    """Codes become names; a code that names no language stays as it is for Download options."""
    assert language_name(code) == name
    assert player.languageName(code) == (name or code)


def test_open_in_another_player_failures_read_plainly(player, tmp_path, monkeypatch):
    """Windows' error text goes to the log; the notice says what happened."""
    notices, logged = [], []
    player.notice.connect(notices.append)
    monkeypatch.setattr("gfgmd.controllers.player_ctrl.write_log", lambda message, level: logged.append(message))
    no_program = OSError(22, "No application is associated with the specified file for this operation")
    no_program.winerror = 1155  # type: ignore[attr-defined]
    for error in (no_program, FileNotFoundError(2, "not found"), PermissionError(13, "denied")):
        def startfile(_path: str, error: OSError = error) -> None:
            raise error
        monkeypatch.setattr("gfgmd.controllers.player_ctrl.os.startfile", startfile, raising=False)
        player.openInSystem(str(tmp_path / "clip.mkv"))
    assert notices == ["Windows has no program set up to play this file.",
                       "The file isn't there any more; it may have been moved or deleted.",
                       "Couldn't open the file in another player."]
    assert len(logged) == 3 and "No application is associated" in logged[0]
    player.logPlaybackError(str(tmp_path / "clip.mkv"), "Could not open codec")
    assert "Could not open codec" in logged[-1]


def test_cover_beside_the_song_is_used(qapp, player, tmp_path):
    song = files(tmp_path, "Song.flac")[0]
    (tmp_path / "Song.jpg").write_bytes(b"jpg")
    player.playAudio([song], 0)
    deadline = time.monotonic() + 10
    while not player.audioCover and time.monotonic() < deadline:
        qapp.processEvents()
    assert player.audioCover.endswith("Song.jpg")


def test_preferences_are_clamped(player):
    player.setVolume(1.7)
    player.setSpeed(1.6)
    player.saveVideoSize(100, 50)
    prefs = load_settings()["player"]
    assert prefs["volume"] == 1.0 and prefs["speed"] == 1.5
    assert (prefs["video_width"], prefs["video_height"]) == (320, 180)
    assert player.trackLabel("Commentary", 0, 2) == "Commentary" and player.trackLabel("", 0, 3) == "Track 3"


def test_version_1_library_gains_playback(tmp_path):
    """A library made before playback positions existed is migrated in place."""
    path = tmp_path / "library.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, filepath TEXT, job_id INTEGER)")
    db.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, url TEXT)")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    store = Store(path)
    try:
        store.save_position("a.mp4", 42.0, 100.0)
        assert store.position_for("a.mp4") == 42.0
    finally:
        store.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    assert "input_path" in [row[1] for row in db.execute("PRAGMA table_info(jobs)")]
    db.close()
