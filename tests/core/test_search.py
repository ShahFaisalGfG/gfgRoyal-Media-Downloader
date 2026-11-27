"""Search from the link box: the yt-dlp command and the results it reads (through the fake yt-dlp)."""

from pathlib import Path

import pytest

from gfgmd.core.analyze import AnalyzeError
from gfgmd.core.runner import run_to_completion
from gfgmd.core.search import MAX_QUERY, clean_query, result_from, search, search_command, search_target
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


def runner(prefix: list[str]):
    def run(command, on_line, stop):
        return run_to_completion(prefix + command[1:], on_line, stop)
    return run


def test_videos_search_youtube_and_songs_youtube_music() -> None:
    assert search_target("  never   gonna ", False, 20) == "ytsearch20:never gonna"
    assert search_target("pasoori ali sethi", True, 20) == "https://music.youtube.com/search?q=pasoori+ali+sethi#songs"
    assert len(clean_query("x " * 500)) <= MAX_QUERY


def test_the_command_reads_only_the_first_results_flat(tmp_path: Path) -> None:
    command = search_command("lofi", True, 20, TOOLS, tmp_path)
    assert "--flat-playlist" in command and command[command.index("--playlist-items") + 1] == "1:20"
    assert command[-2:] == ["--", "https://music.youtube.com/search?q=lofi#songs"]


def test_results_stream_once_each_with_their_details(fake_ytdlp: list[str], tmp_path: Path) -> None:
    arrived = []
    results = search("anything", False, 20, TOOLS, tmp_path, on_result=arrived.append, runner=runner(fake_ytdlp))
    assert [result.id for result in results] == ["sssssssss01", "sssssssss02", "sssssssss03"] and arrived == results
    first = results[0]
    assert (first.channel, first.duration, first.views) == ("Some Channel", 245.0, 1_200_000)
    assert first.thumbnail.endswith("hq720.jpg") and first.url == "https://www.youtube.com/watch?v=sssssssss01"
    assert results[2].live_status == "is_live"


def test_a_failed_search_says_why(fake_ytdlp: list[str], tmp_path: Path) -> None:
    with pytest.raises(AnalyzeError):
        search("fail", False, 20, TOOLS, tmp_path, runner=runner(fake_ytdlp))


def test_songs_link_to_youtube_music_and_get_the_videos_thumbnail() -> None:
    song = result_from({"id": "vKb9xwSRrsU", "title": "Pasoori", "_type": "url"}, music=True)
    assert song is not None and song.url == "https://music.youtube.com/watch?v=vKb9xwSRrsU"
    assert song.thumbnail == "https://i.ytimg.com/vi/vKb9xwSRrsU/hqdefault.jpg" and song.channel == ""
    assert result_from({"title": "No ID"}, music=False) is None
    assert result_from({"id": "UCabc", "_type": "playlist"}, music=False) is None
