"""Reading a link's details: playlists, single videos, item selection, and failures."""

from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.core import analyze as analyze_module
from gfgmd.core.analyze import AnalyzeError, analyze, analyze_list, audio_tracks, estimate_size, items_spec, parse_info
from gfgmd.core.options import DownloadOptions
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("FAKE", "ffmpeg", "ffprobe", "deno")


def test_parse_playlist() -> None:
    info = {"_type": "playlist", "title": "List", "extractor_key": "YoutubeTab", "uploader": "Me",
            "entries": [{"id": "a", "title": "A", "duration": 60, "thumbnails": [{"url": "s", "width": 120},
                                                                                  {"url": "m", "width": 336}]},
                        {"id": "b", "title": "B", "playlist_index": 5, "availability": "private"},
                        {"title": "no id"}]}
    result = parse_info(info)
    assert (result.kind, result.title, result.uploader, result.selectable) == ("playlist", "List", "Me", True)
    assert [(e.id, e.index, e.thumbnail) for e in result.entries] == [("a", 1, "m"), ("b", 5, "")]
    assert result.entries[1].availability == "private"


def test_channel_tabs_are_not_selectable() -> None:
    info = {"_type": "playlist", "title": "Ch", "entries": [{"_type": "url", "id": "UC1", "ie_key": "YoutubeTab"}]}
    assert parse_info(info).selectable is False


def test_parse_video_heights_subtitles_and_size() -> None:
    info = {"id": "v", "title": "V", "duration": 30, "live_status": "not_live",
            "formats": [{"format_id": "137", "vcodec": "avc1", "acodec": "none", "width": 1920, "height": 1080,
                         "filesize": 3000},
                        {"format_id": "136", "vcodec": "avc1", "acodec": "none", "width": 1280, "height": 720,
                         "filesize_approx": 2000},
                        {"format_id": "short", "vcodec": "vp9", "acodec": "none", "width": 1080, "height": 1920},
                        {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "filesize": 500}],
            "subtitles": {"en": [], "live_chat": []}, "automatic_captions": {"ur": [], "de": []}}
    result = parse_info(info, DownloadOptions(max_height=720))
    assert result.kind == "video" and result.heights == [1080, 720]
    assert result.subtitle_langs == ["en"] and result.auto_subtitle_langs == ["de", "ur"]
    assert result.size_estimate == 2000 + 500
    assert estimate_size(info["formats"], DownloadOptions(kind="audio")) == 500


@pytest.mark.parametrize(("indices", "spec"), [([1, 2, 3, 5], "1:3,5"), ([7], "7"), ([], ""), ([3, 1, 2, 2, 9, 10], "1:3,9:10")])
def test_items_spec(indices: list[int], spec: str) -> None:
    assert items_spec(indices) == spec


def fake(prefix: list[str]):
    def run(command, on_line, stop=None, max_line_bytes=1024 * 1024):
        return run_to_completion(prefix + command[1:], on_line, stop, max_line_bytes=max_line_bytes)
    return run


def test_analyze_reads_the_json_line(fake_ytdlp: list[str], tmp_path: Path) -> None:
    logs: list[str] = []
    with patch.object(analyze_module, "run_to_completion", fake(fake_ytdlp + ["--paths", str(tmp_path)])):
        result = analyze("https://fake.test/dump", TOOLS, tmp_path, on_line=logs.append)
    assert result.title == "Fake List" and [entry.id for entry in result.entries] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert any("Downloading webpage" in line for line in logs)


def test_analyze_failure_is_classified(fake_ytdlp: list[str], tmp_path: Path) -> None:
    with patch.object(analyze_module, "run_to_completion", fake(fake_ytdlp + ["--paths", str(tmp_path)])):
        with pytest.raises(AnalyzeError) as error:
            analyze("https://fake.test/private", TOOLS, tmp_path)
    assert error.value.failure.category.key == "private"


def test_audio_tracks_list_dubs_with_the_original_first() -> None:
    """Audio-only formats with languages are the tracks; a combined format's language isn't one."""
    formats = [
        {"format_id": "18", "acodec": "mp4a", "vcodec": "avc1", "language": "en", "format_note": "360p"},
        {"format_id": "251-1", "acodec": "opus", "vcodec": "none", "language": "es", "format_note": "Spanish, medium"},
        {"format_id": "251-0", "acodec": "opus", "vcodec": "none", "language": "en-US",
         "format_note": "English (US) original (default), medium", "language_preference": 10},
        {"format_id": "140-1", "acodec": "mp4a", "vcodec": "none", "language": "es", "format_note": "Spanish, low"},
    ]
    tracks = audio_tracks(formats)
    assert [(t.code, t.label, t.original) for t in tracks] == [("en-US", "English (US)", True),
                                                             ("es", "Spanish", False)]
    assert audio_tracks(formats[:1]) == [] and audio_tracks(formats[2:3]) == []


def test_a_list_read_hands_over_each_video_as_it_arrives(fake_ytdlp: list[str], tmp_path: Path) -> None:
    arrived: list[str] = []
    with patch.object(analyze_module, "run_to_completion", fake(fake_ytdlp + ["--paths", str(tmp_path)])):
        result = analyze_list("https://www.youtube.com/playlist?list=PLfake", TOOLS, tmp_path,
                              on_entry=lambda data: arrived.append(data["id"]))
    assert arrived == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert (result.kind, result.title, result.uploader, result.selectable) == ("playlist", "Fake List", "Fake Channel", True)
    assert [(entry.id, entry.index, entry.duration) for entry in result.entries] == [("aaaaaaaaaaa", 1, 61.0),
                                                                                    ("bbbbbbbbbbb", 2, 62.0)]


def test_a_list_read_that_fails_is_classified(fake_ytdlp: list[str], tmp_path: Path) -> None:
    with patch.object(analyze_module, "run_to_completion", fake(fake_ytdlp + ["--paths", str(tmp_path)])):
        with pytest.raises(AnalyzeError) as error:
            analyze_list("https://fake.test/private", TOOLS, tmp_path)
    assert error.value.failure.category.key == "private"
