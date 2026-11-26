"""Qt's player lets go of a played file once its source is cleared, which the players do when they
close and before a file is deleted; a stopped player alone keeps it open on Windows."""

import math
import os
import struct
import sys
import time
import wave
from pathlib import Path

import pytest

QtMultimedia = pytest.importorskip("PySide6.QtMultimedia")


def _tone(path: Path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(8000 * 2)))


def _held(path: Path) -> bool:
    """True while another handle keeps Windows from renaming the file."""
    moved = path.with_name(path.name + ".moved")
    try:
        os.rename(path, moved)
    except OSError:
        return True
    os.rename(moved, path)
    return False


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to move a file that is open")
def test_clearing_the_source_frees_a_played_file(qapp, tmp_path):
    from PySide6.QtCore import QUrl

    sample = tmp_path / "tone.wav"
    _tone(sample)
    player = QtMultimedia.QMediaPlayer()
    output = QtMultimedia.QAudioOutput()
    output.setVolume(0.0)
    player.setAudioOutput(output)
    player.setSource(QUrl.fromLocalFile(str(sample)))
    player.play()
    deadline = time.monotonic() + 5
    loaded = (QtMultimedia.QMediaPlayer.MediaStatus.LoadedMedia, QtMultimedia.QMediaPlayer.MediaStatus.BufferedMedia,
              QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia, QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia)
    while player.mediaStatus() not in loaded and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    player.stop()
    player.setSource(QUrl())
    assert not _held(sample)
    sample.unlink()
