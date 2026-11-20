"""Extracting a downloaded video's audio: reading the video, the ffmpeg command, tags, and the job itself."""

import base64
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.core import lyrics
from gfgmd.core.extract import (
    AudioExtractor,
    ExtractSpec,
    VideoProbe,
    audio_encoding,
    audio_stem,
    extract_command,
    ffmetadata,
    picture_block,
    read_probe,
    song_tags,
)
from gfgmd.core.options import DownloadOptions
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("yt-dlp", "ffmpeg", "ffprobe", "deno")
PROBE = VideoProbe(duration=6.0, audio_stream=1, audio_codec="aac", tags={"title": "Clip", "artist": "Uploader"})


def audio(**changes) -> DownloadOptions:
    base = {"kind": "audio", "embed_thumbnail": False, "embed_metadata": True, "lyrics": False}
    return DownloadOptions.from_dict({**base, **changes})


def test_reading_the_video_finds_the_original_track_cover_and_tags() -> None:
    probe = read_probe({
        "format": {"duration": "212.5", "tags": {"TITLE": "Song", "artist": "Band", "encoder": "Lavf", "date": ""}},
        "streams": [
            {"index": 0, "codec_type": "video", "codec_name": "h264", "disposition": {"attached_pic": 0}},
            {"index": 1, "codec_type": "audio", "codec_name": "opus", "disposition": {"default": 0}},
            {"index": 2, "codec_type": "audio", "codec_name": "aac", "disposition": {"default": 1}},
            {"index": 3, "codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"index": 4, "codec_type": "attachment", "tags": {"mimetype": "image/jpeg"}},
        ],
    })
    assert (probe.duration, probe.audio_stream, probe.audio_codec) == (212.5, 2, "aac")
    assert (probe.cover_stream, probe.attachment_stream) == (3, 4)
    assert probe.tags == {"title": "Song", "artist": "Band"}  # technical and empty tags stay behind
    silent = read_probe({"format": {}, "streams": [{"index": 0, "codec_type": "video"}]})
    assert silent.audio_stream == -1 and silent.duration == 0.0


def test_formats_bitrates_and_the_original_sound() -> None:
    assert audio_encoding(audio(audio_format="mp3", audio_quality=192), "aac") == ("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"])
    assert audio_encoding(audio(audio_format="vorbis"), "aac") == ("ogg", ["-c:a", "libvorbis", "-b:a", "320k"])
    assert audio_encoding(audio(audio_format="flac"), "aac") == ("flac", ["-c:a", "flac"])
    assert audio_encoding(audio(audio_format="best"), "opus") == ("opus", ["-c:a", "copy"])
    # A track no common audio file holds is kept lossless instead of converted to a lossy format.
    assert audio_encoding(audio(audio_format="best"), "eac3") == ("flac", ["-c:a", "flac"])


def test_names_and_tags_follow_audio_downloads() -> None:
    assert audio_stem(Path("Song (1080p).mp4")) == "Song"
    assert audio_stem(Path("Song (2) (720p).mkv")) == "Song (2)"
    assert audio_stem(Path("Song.webm")) == "Song"
    # The channel stands in for an artist, so an "Artist - Song | labels" title names both.
    tags = song_tags(VideoProbe(tags={"title": "Band - Song | Official Video", "artist": "BandVEVO"}),
                     "ignored", "BandVEVO", "https://youtu.be/x")
    assert (tags["artist"], tags["title"]) == ("Band", "Song")
    assert tags["purl"] == tags["comment"] == "https://youtu.be/x"
    # An artist the site named stays, and so does the whole title.
    named = song_tags(VideoProbe(tags={"title": "Live - Encore", "artist": "Real Artist"}), "", "Some Channel", "")
    assert (named["artist"], named["title"]) == ("Real Artist", "Live - Encore")
    # A video without tags takes its library title and uploader, without " - Topic".
    bare = song_tags(VideoProbe(), "Song", "Band - Topic", "")
    assert (bare["artist"], bare["title"]) == ("Band", "Song") and "purl" not in bare


def test_tag_file_and_picture_block() -> None:
    assert ffmetadata({"title": "a=b;c#d\\e\nf"}) == ";FFMETADATA1\ntitle=a\\=b\\;c\\#d\\\\e\\\nf\n"
    raw = base64.b64decode(picture_block(b"JPEG"))
    kind, mime_length = struct.unpack(">II", raw[:8])
    assert (kind, raw[8:8 + mime_length]) == (3, b"image/jpeg") and raw.endswith(struct.pack(">I", 4) + b"JPEG")


def test_the_command_maps_the_track_cover_tags_and_chapters(tmp_path: Path) -> None:
    video, meta, cover = tmp_path / "v.mp4", tmp_path / "tags.txt", tmp_path / "cover.jpg"
    mp3 = extract_command("ffmpeg", video, PROBE, audio(embed_chapters=True), meta, cover, tmp_path / "a.mp3",
                          ["-c:a", "libmp3lame"])
    assert mp3[mp3.index("-map") + 1] == "0:1" and mp3[mp3.index("-map", mp3.index("-map") + 1) + 1] == "2:0"
    assert mp3[mp3.index("-map_metadata") + 1] == "1" and mp3[mp3.index("-map_chapters") + 1] == "0"
    assert "attached_pic" in mp3 and mp3[mp3.index("-id3v2_version") + 1] == "3" and mp3[-1].endswith("a.mp3")
    # Ogg carries its cover as a tag, WAV beside the file, and without tags nothing is mapped from them.
    ogg = extract_command("ffmpeg", video, PROBE, audio(), None, cover, tmp_path / "a.ogg", ["-c:a", "libvorbis"])
    assert "attached_pic" not in ogg and ogg.count("-i") == 1 and ogg[ogg.index("-map_metadata") + 1] == "-1"
    wav = extract_command("ffmpeg", video, PROBE, audio(embed_chapters=True), meta, cover, tmp_path / "a.wav", [])
    assert wav[wav.index("-map_chapters") + 1] == "-1" and "attached_pic" not in wav


def fake_ffmpeg(code: int = 0, errors: tuple[str, ...] = ()):
    """A runner standing in for ffmpeg: reports progress, writes the output (or fails)."""
    commands = []

    def run(command, on_line, stop):
        commands.append(command)
        on_line("out", "out_time_us=3000000")
        on_line("out", "speed=3.0x")
        for line in errors:
            on_line("err", line)
        if code == 0:
            Path(command[-1]).write_bytes(b"\xff\xfbaudio")
        return code, False
    run.commands = commands
    return run


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "Videos" / "Morning Mix" / "Clip (720p).mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video")
    (path.parent / "Clip (720p).en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    return path


def spec_for(video: Path, tmp_path: Path, **changes) -> ExtractSpec:
    return ExtractSpec(video, audio(**changes), tmp_path / "Music", "Morning Mix", tmp_path / "scratch",
                       item_id="abc", title="Clip", uploader="Uploader", url="https://youtu.be/abc")


def test_extraction_saves_the_song_with_lyrics_from_the_captions(tmp_path: Path, video: Path) -> None:
    runner, saved = fake_ffmpeg(), []
    extractor = AudioExtractor(spec_for(video, tmp_path, lyrics=True), lambda: TOOLS,
                               on_file=lambda info, path: saved.append((info, path)), runner=runner,
                               probe=lambda ffprobe, path: PROBE)
    with patch.object(lyrics, "file_length", return_value=6.0):
        result = extractor.run()
    song = tmp_path / "Music" / "Morning Mix" / "Clip.mp3"
    assert result.state == "done" and result.files == [song] and song.is_file()
    assert saved[0][0]["webpage_url"] == "https://youtu.be/abc" and saved[0][1] == song
    assert "[00:01.00]Hello" in song.with_suffix(".lrc").read_text(encoding="utf-8")
    assert not list((tmp_path / "Music" / ".incomplete").rglob("*.mp3")) and extractor.partial_files() == set()
    assert not (tmp_path / "scratch" / "extract").exists()
    snap = extractor.snapshot()
    assert snap.overall == 0.5 and snap.eta == 1 and snap.stage == "Adding lyrics"


def test_failures_name_the_cause(tmp_path: Path, video: Path) -> None:
    def run(spec, runner, probe=PROBE):
        return AudioExtractor(spec, lambda: TOOLS, runner=runner, probe=lambda ffprobe, path: probe).run()

    full = run(spec_for(video, tmp_path), fake_ffmpeg(1, ("Error: No space left on device",)))
    assert full.state == "disk_full" and full.failure.category.key == "disk_full"
    broken = run(spec_for(video, tmp_path), fake_ffmpeg(1, ("Invalid data found when processing input",)))
    assert broken.failure.category.key == "postprocess" and "Invalid data" in broken.failure.text
    silent = run(spec_for(video, tmp_path), fake_ffmpeg(), VideoProbe(duration=5.0))
    assert silent.state == "failed" and silent.failure.category.key == "no_audio"
    gone = run(spec_for(tmp_path / "missing.mp4", tmp_path), fake_ffmpeg())
    assert gone.failure.category.key == "source_missing"
    assert not list((tmp_path / "Music").rglob("*.mp3"))


def test_a_stopped_extraction_reports_its_unfinished_file(tmp_path: Path, video: Path) -> None:
    def stopped(command, on_line, stop):
        Path(command[-1]).write_bytes(b"half")
        return 1, True
    extractor = AudioExtractor(spec_for(video, tmp_path), lambda: TOOLS, runner=stopped,
                               probe=lambda ffprobe, path: PROBE)
    result = extractor.run()
    partial = tmp_path / "Music" / ".incomplete" / "Morning Mix" / "Clip [abc] (requested-audio-mp3-320k).mp3"
    assert result.state == "stopped" and extractor.partial_files() == {str(partial)} and partial.is_file()
