"""Clean file names, measured quality labels, and staying inside the download folder."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gfgmd.core import naming


def test_normalize_downloads_preserves_same_title_videos(tmp_path: Path) -> None:
    """Use actual quality and preserve videos that share a title (the original script's sweep)."""
    media_dir = tmp_path / "A playlist"
    media_dir.mkdir()
    archive = tmp_path / ".archives" / "list-1080p.txt"
    archive.parent.mkdir()
    archive.write_text("youtube aaaaaaaaaaa\nyoutube bbbbbbbbbbb\nyoutube ccccccccccc\n", encoding="utf-8")
    for name in (
        "001 - Episode [Urdu Dubbed] [aaaaaaaaaaa].mp4",
        "Episode [Urdu Dubbed] [bbbbbbbbbbb] (requested-1080p).mp4",
        "Clip [ccccccccccc] (requested-1080p).mp4",
        "Clip (720p).mp4",
        "Unfinished [ddddddddddd] (requested-1080p).mp4",
    ):
        (media_dir / name).write_bytes(b"video")

    def quality(video: Path, ffprobe: str) -> int:
        return 720 if video.name.startswith("Clip ") else 1080

    with patch.object(naming, "video_quality", side_effect=quality):
        renamed = naming.normalize_downloads(tmp_path, archive, "ffprobe")

    assert renamed == 3
    assert {path.name for path in media_dir.iterdir()} == {
        "Episode [Urdu Dubbed] (1080p).mp4",
        "Episode [Urdu Dubbed] (2) (1080p).mp4",
        "Clip (720p).mp4",
        "Clip (2) (720p).mp4",
        "Unfinished [ddddddddddd] (requested-1080p).mp4",
    }


@pytest.mark.parametrize("dimensions", ("720,1280\n", "1280,720\n"))
def test_video_quality_uses_shorter_dimension(dimensions: str, tmp_path: Path) -> None:
    """Label portrait and landscape videos by their shorter dimension."""
    video = tmp_path / "portrait.mp4"
    with patch.object(naming.subprocess, "run",
                      return_value=SimpleNamespace(returncode=0, stdout=dimensions, stderr="")) as probe:
        assert naming.video_quality(video, "ffprobe") == 720
    assert probe.call_args.args[0][-1] == str(video)


def test_video_quality_rejects_missing_dimensions(tmp_path: Path) -> None:
    """Leave a staged file for retry when ffprobe cannot identify the video."""
    with patch.object(naming.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        with pytest.raises(RuntimeError, match="no video dimensions"):
            naming.video_quality(tmp_path / "bad.mp4", "ffprobe")


def test_finalize_renames_video_and_subtitles(tmp_path: Path) -> None:
    """Rename a finished video and its subtitle files together, without overwriting a namesake."""
    folder = tmp_path / "Single Videos"
    folder.mkdir()
    staged = folder / "Talk [aaaaaaaaaaa] (requested-1080p).mkv"
    staged.write_bytes(b"v")
    (folder / "Talk [aaaaaaaaaaa] (requested-1080p).en.srt").write_text("1")
    (folder / "Talk (720p).mkv").write_bytes(b"older")
    with patch.object(naming, "video_quality", return_value=720):
        final = naming.finalize_file(staged, tmp_path, "ffprobe", label_quality=True)
    assert final.name == "Talk (2) (720p).mkv"
    assert (folder / "Talk (2) (720p).en.srt").exists()
    assert (folder / "Talk (720p).mkv").read_bytes() == b"older"


def test_finalize_audio_has_no_quality_label(tmp_path: Path) -> None:
    """Name audio by title only, keeping a date or number prefix."""
    staged = tmp_path / "2024-01-02 - Song [x_y-z] (requested-audio-mp3).mp3"
    staged.write_bytes(b"a")
    final = naming.finalize_file(staged, tmp_path.parent, "ffprobe", label_quality=True)
    assert final.name == "2024-01-02 - Song.mp3"


def test_finalize_leaves_files_outside_the_root_alone(tmp_path: Path) -> None:
    """Never rename a reported path outside the download folder."""
    outside = tmp_path / "elsewhere" / "Talk [aaaaaaaaaaa] (requested-1080p).mp4"
    outside.parent.mkdir()
    outside.write_bytes(b"v")
    root = tmp_path / "root"
    root.mkdir()
    assert naming.finalize_file(outside, root, "ffprobe", label_quality=False) == outside
    assert outside.exists()


def test_inside_root(tmp_path: Path) -> None:
    """Resolve .. before deciding."""
    root = tmp_path / "root"
    root.mkdir()
    assert naming.inside_root(root / "a" / "b.mp4", root)
    assert not naming.inside_root(root / ".." / "b.mp4", root)
    assert not naming.inside_root(tmp_path / "rootx" / "b.mp4", root)


def test_format_labels_for_the_lists() -> None:
    """The file's own type once it exists, else the one asked for; nothing for the site's original audio."""
    assert naming.format_label("C:/Music/Song.mp3") == "MP3"
    assert naming.format_label("", {"kind": "audio", "audio_format": "vorbis"}) == "OGG"
    assert naming.format_label("", {"kind": "audio", "audio_format": "best"}) == ""
    assert naming.format_label("", {"kind": "video", "container": "mkv"}) == "MKV"
    assert naming.format_label("C:/Videos/Talk (1080p).webm", {"kind": "video", "container": "mp4"}) == "WEBM"
