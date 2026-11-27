"""Spotify links: the embed page's list, spotDL for long playlists, matching on YouTube, and downloading."""

import json
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.core import naming
from gfgmd.core.archive import archive_path
from gfgmd.core.command import RunPaths
from gfgmd.core.jobs import JobSpec
from gfgmd.core.options import DownloadOptions
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import source_from_url
from gfgmd.core.spotify import (EMBED_LIMIT, Candidate, SpotifyError, SpotifyExecutor, SpotifySong, best_match,
                                link_parts, match_songs, parse_embed, parse_spotdl, picked, read_list, read_page,
                                score, song_tags, to_analysis)
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("FAKE-YT-DLP", "FAKE-FFMPEG", "FAKE-FFPROBE", "deno")
WITH_SPOTDL = ToolSet("FAKE-YT-DLP", "FAKE-FFMPEG", "FAKE-FFPROBE", "deno", spotdl="FAKE-SPOTDL")
ALBUM_ID, PLAYLIST_ID, TRACK_ID = "4aawyAB9vmqN3uQ7FjRGTy", "37i9dQZF1DXcBWIGoYBM5M", "7fmpKF0rLGPnP7kcQ5ZMm7"


def embed_page(entity: dict) -> str:
    """A page shaped like Spotify's embed page, with the entity in its __NEXT_DATA__ script."""
    data = {"props": {"pageProps": {"state": {"data": {"entity": entity}}}}}
    return ('<html><head></head><body><script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(data)}</script></body></html>")


def row(number: int, title: str, artists: str = "Fake Artist", seconds: int = 200) -> dict:
    return {"uri": f"spotify:track:{number:022d}", "title": title, "subtitle": artists, "duration": seconds * 1000,
            "entityType": "track"}


def album_page(*titles: str) -> str:
    return embed_page({
        "type": "album", "id": ALBUM_ID, "name": "Fake Album", "subtitle": "Fake Artist",
        "releaseDate": {"isoString": "2012-11-16T00:00:00Z"},
        "visualIdentity": {"image": [{"url": "https://i.scdn.co/image/small", "maxWidth": 64},
                                     {"url": "https://i.scdn.co/image/large", "maxWidth": 640}]},
        "trackList": [row(number, title) for number, title in enumerate(titles, start=1)]})


def playlist_page(count: int) -> str:
    return embed_page({
        "type": "playlist", "id": PLAYLIST_ID, "name": "Long Mix", "subtitle": "Someone",
        "coverArt": {"sources": [{"url": "https://i.scdn.co/image/mix", "width": 300}]},
        "trackList": [row(number, f"Song {number}", "Fake Artist, Guest") for number in range(1, count + 1)]})


def track_page() -> str:
    return embed_page({
        "type": "track", "id": TRACK_ID, "name": "Back in Time", "duration": 207_000,
        "artists": [{"name": "Pitbull"}], "releaseDate": {"isoString": "2012-11-16T00:00:00Z"},
        "visualIdentity": {"image": [{"url": "https://i.scdn.co/image/back", "maxWidth": 640}]}})


# ── Links ─────────────────────────────────────────────────────────────────

def test_spotify_links_classify_by_what_they_hold():
    album = source_from_url(f"https://open.spotify.com/intl-de/album/{ALBUM_ID}?si=abc")
    assert (album.kind, album.source_id, album.site) == ("playlist", f"https://open.spotify.com/album/{ALBUM_ID}", "spotify")
    track = source_from_url(f"https://open.spotify.com/track/{TRACK_ID}")
    assert (track.kind, track.is_collection) == ("video", False)
    assert link_parts(track.source_id) == ("track", TRACK_ID)
    with pytest.raises(ValueError, match="Only Spotify playlists, albums, and songs"):
        source_from_url("https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg")
    with pytest.raises(ValueError, match="share link"):
        source_from_url("https://spotify.link/AbCdEf")


# ── Reading the list ──────────────────────────────────────────────────────

def test_an_albums_page_names_its_songs_in_order():
    listed = parse_embed(album_page("First", "Second"))
    assert (listed.kind, listed.title, listed.owner, listed.cover, listed.complete) == (
        "album", "Fake Album", "Fake Artist", "https://i.scdn.co/image/large", True)
    first = listed.songs[0]
    assert (first.title, first.artists, first.duration, first.track_number, first.album, first.year) == (
        "First", ("Fake Artist",), 200.0, 1, "Fake Album", "2012")
    assert listed.songs[1].track_number == 2 and first.url == f"https://open.spotify.com/track/{1:022d}"


def test_a_playlists_page_splits_artists_and_stops_at_100():
    listed = parse_embed(playlist_page(EMBED_LIMIT))
    assert listed.complete is False and len(listed.songs) == EMBED_LIMIT
    song = listed.songs[0]
    assert song.artists == ("Fake Artist", "Guest") and song.track_number == 0 and song.album == ""
    assert song.name == "Fake Artist, Guest - Song 1" and song.query == "Fake Artist - Song 1"
    assert parse_embed(playlist_page(12)).complete is True


def test_a_songs_page_is_one_song():
    listed = parse_embed(track_page())
    assert listed.kind == "track" and listed.owner == "Pitbull"
    assert listed.songs == [SpotifySong(TRACK_ID, "Back in Time", ("Pitbull",), 207.0, year="2012",
                                        cover="https://i.scdn.co/image/back")]


def test_a_page_without_a_list_is_refused():
    with pytest.raises(ValueError):
        parse_embed("<html>Sorry, Spotify isn't available</html>")
    with pytest.raises(ValueError):
        parse_embed(embed_page({"type": "artist", "name": "Pitbull"}))


def spotdl_runner(count: int, calls: list):
    """A runner standing in for spotDL's save run: it writes `count` songs to the --save-file."""
    def run(command, on_line, stop=None, env=None):
        calls.append((command, env))
        save = Path(command[command.index("--save-file") + 1])
        save.write_text(json.dumps([
            {"song_id": f"{number:022d}", "name": f"Song {number}", "artists": ["Fake Artist"], "duration": 200,
             "album_name": "Some Album", "year": "2020", "track_number": 3, "cover_url": "https://i.scdn.co/image/a",
             "list_url": f"https://open.spotify.com/playlist/{PLAYLIST_ID}"} for number in range(1, count + 1)]),
            encoding="utf-8")
        return 0, False
    return run


def test_a_playlist_past_100_songs_is_read_whole_by_spotdl(tmp_path):
    calls = []
    listed = read_list(f"https://open.spotify.com/playlist/{PLAYLIST_ID}", WITH_SPOTDL, tmp_path / "home",
                       DownloadOptions(kind="audio", proxy="http://proxy.test:8080"),
                       page=lambda url: playlist_page(EMBED_LIMIT), runner=spotdl_runner(130, calls))
    assert listed.complete and len(listed.songs) == 130 and listed.title == "Long Mix"
    assert listed.songs[0].album == "Some Album" and listed.songs[0].track_number == 0  # a playlist's song
    command, env = calls[0]
    assert command[:3] == ["FAKE-SPOTDL", "save", f"https://open.spotify.com/playlist/{PLAYLIST_ID}"]
    assert command[command.index("--proxy") + 1] == "http://proxy.test:8080"
    # spotDL's settings and cache stay in a folder of the app's, not the user's home.
    assert env["USERPROFILE"] == env["HOME"] == str(tmp_path / "home")


def test_without_spotdl_a_long_playlist_keeps_its_first_100_songs(tmp_path):
    calls = []
    listed = read_list(f"https://open.spotify.com/playlist/{PLAYLIST_ID}", TOOLS, tmp_path, DownloadOptions(),
                       page=lambda url: playlist_page(EMBED_LIMIT), runner=spotdl_runner(130, calls))
    assert not listed.complete and len(listed.songs) == EMBED_LIMIT and calls == []


def test_a_short_list_never_waits_for_spotdl(tmp_path):
    calls = []
    listed = read_list(f"https://open.spotify.com/album/{ALBUM_ID}", WITH_SPOTDL, tmp_path, DownloadOptions(),
                       page=lambda url: album_page("A", "B"), runner=spotdl_runner(2, calls))
    assert len(listed.songs) == 2 and calls == []


def test_spotdl_reads_the_list_when_the_page_cant_be_read(tmp_path):
    def broken(url):
        raise ValueError("Spotify's page changed")
    listed = read_list(f"https://open.spotify.com/album/{ALBUM_ID}", WITH_SPOTDL, tmp_path, DownloadOptions(),
                       page=broken, runner=spotdl_runner(3, []))
    assert len(listed.songs) == 3 and listed.title == "Some Album"
    with pytest.raises(SpotifyError) as unreadable:
        read_list(f"https://open.spotify.com/album/{ALBUM_ID}", TOOLS, tmp_path, DownloadOptions(), page=broken)
    assert unreadable.value.failure.category.key == "spotify_unreadable"

    def offline(url):
        raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")
    with pytest.raises(SpotifyError) as dropped:
        read_list(f"https://open.spotify.com/album/{ALBUM_ID}", TOOLS, tmp_path, DownloadOptions(), page=offline)
    assert dropped.value.failure.category.key == "network"


def test_spotdls_save_file_skips_rows_without_an_id():
    songs = parse_spotdl(json.dumps([{"song_id": "x" * 22, "name": "Song", "artists": ["A", "B"], "duration": 61,
                                      "list_url": f"https://open.spotify.com/album/{ALBUM_ID}", "track_number": 4,
                                      "year": "2001-05-01"}, {"name": "No ID"}, "junk"]))
    assert songs == [SpotifySong("x" * 22, "Song", ("A", "B"), 61.0, track_number=4, year="2001")]


# ── Matching ──────────────────────────────────────────────────────────────

SONG = SpotifySong("1" * 22, "Back in Time", ("Pitbull",), 207.0)


@pytest.mark.parametrize(("candidate", "better_than"), [
    # The released recording beats the official video with its longer intro.
    (Candidate("a", "Pitbull - Back in Time [Audio]", "Pitbull", 207), Candidate("v", "Pitbull - Back in Time (Official Video)", "Pitbull", 213)),
    # YouTube's own "Topic" copy is preferred.
    (Candidate("t", "Back in Time", "Pitbull - Topic", 207), Candidate("u", "Pitbull - Back in Time", "Some Uploader", 207)),
    # A live version, a remix, or a cover is marked down unless the Spotify title names it.
    (Candidate("a", "Pitbull - Back in Time", "Pitbull", 207), Candidate("l", "Pitbull - Back in Time (Live)", "Pitbull", 207)),
    (Candidate("a", "Pitbull - Back in Time", "Pitbull", 207), Candidate("r", "Back in Time (Pitbull Remix)", "DJ Some", 207)),
])
def test_scoring_prefers_the_released_recording(candidate, better_than):
    assert score(SONG, candidate) > score(SONG, better_than)


def test_the_artists_own_upload_beats_a_fan_upload():
    """Spotify's "Men In Black 3" is YouTube's "Men In Black III"; a fan's copy a second off loses."""
    song = SpotifySong("1" * 22, 'Back in Time - featured in "Men In Black 3"', ("Pitbull",), 207.0)
    official = Candidate("o", 'Pitbull - Back in Time (featured in "Men In Black III") [Audio]', "Pitbull", 207)
    fan = Candidate("f", "men in black 3 song back in time pitbull mp3", "dennis schmitt", 206)
    assert best_match(song, [fan, official]) == official


def test_a_result_too_long_or_too_short_is_never_taken():
    assert score(SONG, Candidate("x", "Pitbull - Back in Time", "Pitbull", 207 + 16)) == 0.0
    assert best_match(SONG, [Candidate("x", "Pitbull - Back in Time", "Pitbull", 250)]) is None
    assert best_match(SONG, [Candidate("y", "Something Else Entirely", "Nobody", 207)]) is None
    # An unknown length neither helps nor rules out.
    assert best_match(SONG, [Candidate("z", "Pitbull - Back in Time", "Pitbull - Topic", 0)]) is not None


def test_songs_are_matched_in_batches_through_one_search_each(fake_ytdlp, tmp_path):
    songs = [SpotifySong(f"{number:022d}", f"Song {number}", ("Fake Artist",), 200.0) for number in range(1, 26)]
    songs.append(SpotifySong("n" * 22, "Nowhere", ("Nowhere Man",), 200.0))
    seen = []

    def runner(command, on_line, stop):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    matched = match_songs(songs, TOOLS, tmp_path / "cache", DownloadOptions(kind="audio"), runner,
                          on_progress=seen.append)
    assert len(matched) == 25 and "n" * 22 not in matched
    assert all(candidate.id.endswith("a") for candidate in matched.values())  # the Topic copy, 200 s
    assert len(seen) == 2 and seen[-1] == 26  # two runs of up to 20 songs each


def test_picked_positions_choose_the_songs():
    songs = [SpotifySong(str(number), f"Song {number}", (), 0) for number in range(1, 11)]
    assert [song.id for song in picked(songs, "")] == [str(number) for number in range(1, 11)]
    assert [song.id for song in picked(songs, "1:3,8")] == ["1", "2", "3", "8"]
    assert [song.id for song in picked(songs, "9:")] == ["9", "10"]


def test_an_albums_songs_get_their_place_on_it():
    listed = parse_embed(album_page("First", "Second", "Third"))
    assert song_tags(listed.songs[1], listed) == {
        "title": "Second", "artist": "Fake Artist", "album": "Fake Album", "date": "2012", "track": "2/3",
        "album_artist": "Fake Artist"}
    playlist = parse_embed(playlist_page(3))
    assert "track" not in song_tags(playlist.songs[0], playlist)


# ── Downloading ───────────────────────────────────────────────────────────

@pytest.fixture
def album_spec(tmp_path):
    url = f"https://open.spotify.com/album/{ALBUM_ID}"
    source = source_from_url(url)
    options = DownloadOptions(kind="audio", lyrics=False)
    root = tmp_path / "Music"
    paths = RunPaths(root, archive_path(root, source, options.profile), root / ".gfgmd" / "jobs" / "s", tmp_path / "cache")
    return JobSpec(url, source, options, paths, retry_delay=1)


def test_an_album_downloads_its_found_songs_named_and_listed(fake_ytdlp, album_spec, tmp_path):
    saved, covers = [], []

    def runner(command, on_line, stop=None, env=None):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)

    def cover(url):
        covers.append(url)
        return b"\xff\xd8\xff fake jpeg"
    executor = SpotifyExecutor(album_spec, lambda: TOOLS, tmp_path / "home",
                               on_file=lambda info, path: saved.append((info, path)), runner=runner,
                               page=lambda url: album_page("Song One", "Nowhere", "Song Three"), cover=cover)
    with patch.object(naming, "video_quality", return_value=0):
        result = executor.run()
    assert result.state == "done", result.message
    assert sorted(path.name for path in result.files) == ["Fake Artist - Song One.mp4", "Fake Artist - Song Three.mp4"]
    assert all(path.parent == tmp_path / "Music" / "Fake Album" and path.is_file() for path in result.files)
    assert [failure.category.key for failure in result.skipped] == ["no_match"]
    assert result.message == "2 songs saved, 1 couldn't be downloaded"
    assert {info["title"] for info, _ in saved} == {"Fake Artist - Song One", "Fake Artist - Song Three"}
    assert covers == ["https://i.scdn.co/image/large"]  # fetched once for the album
    updates = dict(executor.take_updates())
    assert updates["list_title"] == "Fake Album"
    # Every song is listed in Spotify's order; the one without a match under its Spotify ID.
    assert [(item["title"], len(item["id"])) for item in updates["listed"]] == [
        ("Fake Artist - Song One", 11), ("Fake Artist - Nowhere", 22), ("Fake Artist - Song Three", 11)]
    # A resumed download doesn't search again: the matches are kept in the job's folder.
    kept = json.loads((album_spec.paths.job_dir / "spotify-matches.json").read_text(encoding="utf-8"))
    assert len(kept) == 2


def test_only_the_picked_songs_download(fake_ytdlp, album_spec, tmp_path):
    def runner(command, on_line, stop=None, env=None):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    spec = replace(album_spec, options=album_spec.options.with_changes(items="3"))
    executor = SpotifyExecutor(spec, lambda: TOOLS, tmp_path / "home", runner=runner,
                               page=lambda url: album_page("Song One", "Nowhere", "Song Three"),
                               cover=lambda url: b"\xff\xd8\xff")
    with patch.object(naming, "video_quality", return_value=0):
        result = executor.run()
    assert [path.name for path in result.files] == ["Fake Artist - Song Three.mp4"] and not result.skipped


def test_a_list_that_cant_be_read_fails_with_its_reason(album_spec, tmp_path):
    def broken(url):
        raise ValueError("changed")
    result = SpotifyExecutor(album_spec, lambda: TOOLS, tmp_path / "home", page=broken).run()
    assert result.state == "failed" and result.failure is not None
    assert result.failure.category.key == "spotify_unreadable" and result.failure.category.action == "update_tools"


def test_stopping_before_the_search_ends_it(album_spec, tmp_path):
    executor = SpotifyExecutor(album_spec, lambda: TOOLS, tmp_path / "home", page=lambda url: album_page("A"))
    executor.stop()
    assert executor.run().state == "stopped"


def test_download_options_show_the_pages_songs():
    analysis = to_analysis(read_page(f"https://open.spotify.com/album/{ALBUM_ID}", page=lambda url: album_page("A", "B")))
    assert (analysis.kind, analysis.title, analysis.uploader, analysis.selectable) == ("playlist", "Fake Album",
                                                                                     "Fake Artist", True)
    assert [(entry.title, entry.index, entry.duration) for entry in analysis.entries] == [
        ("Fake Artist - A", 1, 200.0), ("Fake Artist - B", 2, 200.0)]
    song = to_analysis(read_page(f"https://open.spotify.com/track/{TRACK_ID}", page=lambda url: track_page()))
    assert (song.kind, song.title, song.duration) == ("video", "Pitbull - Back in Time", 207.0)
