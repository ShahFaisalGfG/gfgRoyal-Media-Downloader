"""Lyrics: site captions first, LRCLIB by matching length, the LRC file, and the MP3 lyrics tag.

LRCLIB is a local http.server here; the tests never contact a site.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

import pytest

from gfgmd.core import lyrics
from gfgmd.core.lyrics import Song, add_lyrics, add_uslt, fetch_json, lookup_lrclib, pick_site_lyrics, song_from_info

SYNCED = "[00:01.00]First line\n[00:04.50]Second line\n"
SONGS = [
    {"id": 1, "trackName": "Song", "artistName": "Band", "albumName": "Album", "duration": 200.0,
     "instrumental": False, "plainLyrics": "First line\nSecond line", "syncedLyrics": SYNCED},
    {"id": 2, "trackName": "Song", "artistName": "Band", "albumName": "Live", "duration": 260.0,
     "instrumental": False, "plainLyrics": "Live version", "syncedLyrics": "[00:02.00]Live version\n"},
]


class _LrcLib(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        type(self).requests.append(self.path)
        query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        if self.path.startswith("/api/get"):
            match = [song for song in SONGS if song["albumName"] == query.get("album_name")
                     and abs(song["duration"] - float(query.get("duration", 0))) <= 2]
            body: Any = match[0] if match else None
        else:
            body = [song for song in SONGS if song["trackName"] == query.get("track_name")
                    and song["artistName"] == query.get("artist_name")]
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        return


@pytest.fixture
def lrclib() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LrcLib)
    _LrcLib.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(("info", "expected"), [
    ({"title": "Song (Official Music Video)", "uploader": "Band - Topic", "duration": 200},
     Song("Song", "Band", "", 200.0)),
    ({"title": "Band - Song [Lyrics]", "uploader": "Some Channel", "duration": 200},
     Song("Song", "Band", "", 200.0)),
    ({"title": "Song (Remastered 2011) (4K)", "artist": "Band", "album": "Album", "track": "Song"},
     Song("Song", "Band", "Album", 0.0)),
    ({"title": "Song", "uploader": "BandVEVO"}, Song("Song", "Band", "", 0.0)),
    ({"title": "Janji - Heroes Tonight (feat. Johnning) | Progressive House | NCS - Copyright Free Music",
      "uploader": "NoCopyrightSounds", "duration": 208},
     Song("Heroes Tonight (feat. Johnning)", "Janji", "", 208.0)),
    ({"title": "Song [NCS Release]", "artist": "Band"}, Song("Song", "Band", "", 0.0)),
])
def test_song_details_are_cleaned(info: dict[str, Any], expected: Song) -> None:
    assert song_from_info(info) == expected


def test_featured_artists_are_looked_up_without_feat(lrclib: str) -> None:
    """LRCLIB lists "Song", not "Song (feat. Guest)"; the lookup tries the shorter title first."""
    synced, _plain = lookup_lrclib(Song("Song (feat. Guest)", "Band", "", 200.0), fetch_json, lrclib)
    assert synced == SYNCED
    assert any("track_name=Song&" in path for path in _LrcLib.requests)


def test_lrclib_takes_only_a_matching_length(lrclib: str) -> None:
    """The 200 s studio version fits a 201 s file; the 260 s live one never does."""
    synced, plain = lookup_lrclib(Song("Song", "Band", "Album", 201.0), fetch_json, lrclib)
    assert synced == SYNCED and plain == "First line\nSecond line"
    assert lookup_lrclib(Song("Song", "Band", "", 230.0), fetch_json, lrclib) == ("", "")
    assert lookup_lrclib(Song("Unknown", "Nobody", "", 100.0), fetch_json, lrclib) == ("", "")
    assert lookup_lrclib(Song("", "Band", "", 200.0), fetch_json, lrclib) == ("", "")


def test_site_captions_win_and_become_the_lrc(tmp_path: Path) -> None:
    """The site's caption file in the preferred language becomes "<song>.lrc"; nothing is looked up."""
    audio = tmp_path / "Song.mp3"
    audio.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" * 10)
    (tmp_path / "Song.ur.lrc").write_text("[00:02.00]Urdu line\n", encoding="utf-8")
    (tmp_path / "Song.en-US.lrc").write_text("[00:01.00]English line\n", encoding="utf-8")
    assert pick_site_lyrics(audio, "en.*,ur") == tmp_path / "Song.en-US.lrc"

    def no_network(url: str) -> Any:
        raise AssertionError(f"looked up {url}")

    result = add_lyrics(audio, {"title": "Song", "uploader": "Band"}, "en.*,ur", True, "ffmpeg-missing",
                        "ffprobe-missing", no_network)
    assert (result.source, result.synced, result.embedded) == ("site", True, True)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Song.lrc", "Song.mp3"]
    assert "[00:01.00]English line" in (tmp_path / "Song.lrc").read_text(encoding="utf-8")
    assert "English line".encode("utf-8") in audio.read_bytes()


def test_lrclib_fills_in_and_offline_is_harmless(tmp_path: Path, lrclib: str,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lyrics, "file_length", lambda ffprobe, path: 200.5)
    audio = tmp_path / "Song.m4a"
    audio.write_bytes(b"not really audio")
    info = {"title": "Song", "artist": "Band", "album": "Album"}
    result = add_lyrics(audio, info, "en.*", True, "ffmpeg-missing", "ffprobe-missing", fetch_json, lrclib)
    assert result.source == "lrclib" and result.synced and not result.embedded  # no ffmpeg here to tag M4A
    assert (tmp_path / "Song.lrc").read_text(encoding="utf-8") == SYNCED

    def offline(url: str) -> Any:
        raise OSError("no network")

    (tmp_path / "Song.lrc").unlink()
    result = add_lyrics(audio, info, "en.*", True, "ffmpeg-missing", "ffprobe-missing", offline)
    assert result.source == "" and not (tmp_path / "Song.lrc").exists()
    result = add_lyrics(audio, info, "en.*", False, "ffmpeg-missing", "ffprobe-missing", fetch_json, lrclib)
    assert result.source == "" and len(_LrcLib.requests) == 1  # only the first lookup reached LRCLIB


@pytest.mark.parametrize("major", [3, 4])
def test_uslt_frame_replaces_the_old_one(tmp_path: Path, major: int) -> None:
    """Lyrics go into the existing ID3 tag; other frames and the audio stay intact."""
    title = b"\x03Title" if major == 4 else b"\x00Title"
    size = len(title)
    frame_size = (size.to_bytes(4, "big") if major == 3
                  else bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]))
    frame = b"TIT2" + frame_size + b"\x00\x00" + title
    tag = frame + b"\x00" * 20
    tag_size = bytes([0, 0, (len(tag) >> 7) & 0x7F, len(tag) & 0x7F])
    audio = b"\xff\xfb\x90\x00" * 50
    path = tmp_path / "a.mp3"
    path.write_bytes(b"ID3" + bytes([major, 0, 0]) + tag_size + tag + audio)
    assert add_uslt(path, "old words") and add_uslt(path, "new wörds")
    data = path.read_bytes()
    assert data.endswith(audio) and data.count(b"TIT2") == 1 and data.count(b"USLT") == 1
    words = "new wörds".encode("utf-8" if major == 4 else "utf-16-le")
    assert words in data and b"old" not in data and data[3] == major


def test_uslt_skips_tags_it_does_not_handle(tmp_path: Path) -> None:
    path = tmp_path / "a.mp3"
    original = b"ID3\x04\x00\x80\x00\x00\x00\x00" + b"\xff\xfb" * 4  # unsynchronised
    path.write_bytes(original)
    assert not add_uslt(path, "words") and path.read_bytes() == original
    bare = tmp_path / "b.mp3"
    bare.write_bytes(b"\xff\xfb" * 4)
    assert add_uslt(bare, "words") and bare.read_bytes().startswith(b"ID3\x04")
