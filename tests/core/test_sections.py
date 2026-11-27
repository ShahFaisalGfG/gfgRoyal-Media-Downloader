"""Part of a video and one file per chapter: the times people type, the names files get, and the
yt-dlp options each choice becomes."""

from pathlib import Path

import pytest

from gfgmd.core.command import CHAPTERS_FOLDER, RunPaths, download_command
from gfgmd.core.options import DownloadOptions, clock_label, parse_time
from gfgmd.core.sources import source_from_url
from gfgmd.core.tags import retag_command
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe")
VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def command(tmp_path: Path, **options) -> list[str]:
    paths = RunPaths(tmp_path, tmp_path / ".archives" / "a.txt", tmp_path / "job", tmp_path / "cache")
    return download_command(VIDEO, source_from_url(VIDEO), DownloadOptions(**options).validate(), TOOLS, paths)


def value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


@pytest.mark.parametrize("text, seconds", [("90", 90), ("1:30", 90), ("01:02:30", 3750), ("1:30.5", 90.5),
                                           ("0", 0), (" 2:00 ", 120)])
def test_times_are_read_as_people_type_them(text: str, seconds: float) -> None:
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["", "1:75", "1:2:3:4", "abc", "-5", "1:30:", "1.5:00"])
def test_times_that_cant_be_read_say_how_to_type_them(text: str) -> None:
    with pytest.raises(ValueError, match="such as 1:30"):
        parse_time(text)


def test_clock_labels_have_no_colons() -> None:
    assert [clock_label(s) for s in (45, 83, 3723, 59.9)] == ["45s", "1m23s", "1h02m03s", "59s"]


def test_a_part_must_end_after_it_starts_and_stands_alone() -> None:
    with pytest.raises(ValueError, match="end after it starts"):
        DownloadOptions(section_start="5:00", section_end="1:00").validate()
    with pytest.raises(ValueError, match="not both"):
        DownloadOptions(section_start="1:00", split_chapters=True).validate()
    with pytest.raises(ValueError, match="live stream"):
        DownloadOptions(section_start="1:00", live_from_start=True).validate()
    assert DownloadOptions(section_end="2:00").section == (0.0, 120.0)
    assert DownloadOptions(section_start="2:00").section_label == "2m00s-end"


def test_parts_and_chapters_are_files_of_their_own() -> None:
    """Their archive and staged name differ from the whole video's, so neither stands in for the other."""
    assert DownloadOptions(section_start="1:00").profile == "1080p-part"
    assert DownloadOptions(split_chapters=True).profile == "1080p-ch"
    longest = DownloadOptions(kind="audio", audio_format="vorbis", audio_quality=320, section_start="1")
    assert len(longest.profile) <= 24  # the staged-name pattern allows 24 characters
    saved = DownloadOptions(section_start="1:05", section_end="2:10", exact_cut=True)
    assert DownloadOptions.from_dict(saved.to_dict()) == saved


def test_a_part_downloads_only_its_times_and_keeps_no_archive(tmp_path: Path) -> None:
    cmd = command(tmp_path, section_start="1:05", section_end="2:10.5", exact_cut=True, sponsorblock="remove",
                  embed_chapters=True)
    assert value(cmd, "--download-sections") == "*65-130.5" and "--force-keyframes-at-cuts" in cmd
    assert "--no-download-archive" in cmd and "--download-archive" not in cmd
    assert "(1m05s-2m10s) [%(id).64B]" in value(cmd, "--output")
    # SponsorBlock's times are the whole video's: a part has them marked, never cut.
    assert value(cmd, "--sponsorblock-mark") and "--sponsorblock-remove" not in cmd
    assert "--embed-chapters" not in cmd
    to_end = command(tmp_path, kind="audio", section_start="30")
    assert value(to_end, "--download-sections") == "*30-inf" and "--force-keyframes-at-cuts" not in to_end
    assert "--write-subs" not in to_end  # a part has no captions that line up with it


def test_chapters_are_staged_by_video_and_skip_the_whole_videos_captions(tmp_path: Path) -> None:
    cmd = command(tmp_path, kind="audio", split_chapters=True, embed_chapters=True)
    template = next(arg for arg in cmd if arg.startswith("chapter:"))
    assert "--split-chapters" in cmd and f"/{CHAPTERS_FOLDER}%(id).64B/%(section_number)03d " in template
    assert template.endswith("(requested-audio-mp3-320k-ch).%(ext)s")
    assert "--write-subs" not in cmd and "--embed-chapters" not in cmd
    assert value(cmd, "--download-archive").endswith("a.txt")  # chapters keep the archive


def test_retagging_keeps_every_stream_and_replaces_only_the_cover(tmp_path: Path) -> None:
    song, target, cover = tmp_path / "a.mp3", tmp_path / "b.mp3", tmp_path / "c.jpg"
    plain = retag_command("ffmpeg", song, target, {"title": "Intro", "track": "1/3"})
    assert plain[plain.index("-map") + 1] == "0" and "-c" in plain and "-id3v2_version" in plain
    assert ["-metadata", "title=Intro"] == plain[plain.index("title=Intro") - 1:plain.index("title=Intro") + 1]
    covered = retag_command("ffmpeg", song, target, {"title": "Intro"}, cover)
    assert covered[covered.index("-map") + 1] == "0:a" and "attached_pic" in covered
    opus = retag_command("ffmpeg", tmp_path / "a.opus", tmp_path / "b.opus", {"title": "Intro"}, cover)
    # Opus keeps its own picture and gets the title on its stream too (Vorbis comments).
    assert "attached_pic" not in opus and "-metadata:s:a:0" in opus
