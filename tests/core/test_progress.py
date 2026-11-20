"""Output parsing and the progress snapshot."""

import json

from gfgmd.core.progress import ProgressTracker, parse_line, read_convert_progress


def dl(done: int, total: int, fmt: str, vcodec: str, acodec: str, status: str = "downloading") -> str:
    return "@@gfgr:dl " + json.dumps({
        "p": {"status": status, "downloaded_bytes": done, "total_bytes": total, "speed": 1024.0, "eta": 3,
              "fragment_index": 2, "fragment_count": 10},
        "i": {"id": "aaaaaaaaaaa", "format_id": fmt, "vcodec": vcodec, "acodec": acodec}})


def test_parse_kinds() -> None:
    """Recognize the app's lines, errors with their item, warnings, and plain log lines."""
    assert parse_line("out", '@@gfgr:item {"id":"x","title":"T"}').data == {"id": "x", "title": "T"}
    error = parse_line("err", "ERROR: [youtube] abcdefghijk: Private video")
    assert error.kind == "error" and error.data == {"extractor": "youtube", "id": "abcdefghijk"}
    assert parse_line("err", "WARNING: something").kind == "warning"
    assert parse_line("out", "[youtube] Extracting URL").kind == "log"


def test_parse_tolerates_na_and_bad_json() -> None:
    """Treat yt-dlp's NA as missing and keep going on a damaged line."""
    assert parse_line("out", "@@gfgr:parts NA").data == {"parts": []}
    assert parse_line("out", '@@gfgr:dl {"p":NA,"i":{"id":"x"}}').data == {"p": None, "i": {"id": "x"}}
    assert parse_line("out", "@@gfgr:file {broken").data == {}


def test_two_part_download_weights_by_size() -> None:
    """Weight video and audio parts by their sizes and name the current stage."""
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"aaaaaaaaaaa","title":"Clip","live_status":"not_live"}')
    tracker.feed("out", '@@gfgr:parts [{"format_id":"137","filesize":3000},{"format_id":"140","filesize":1000}]')
    tracker.feed("out", dl(1500, 3000, "137", "avc1", "none"))
    snap = tracker.snapshot()
    assert snap.stage == "Downloading video"
    assert snap.downloaded == 1500 and snap.total == 4000
    assert snap.fragment == "2/10" and snap.speed == 1024.0 and snap.eta == 3
    tracker.feed("out", dl(3000, 3000, "137", "avc1", "none", "finished"))
    tracker.feed("out", dl(500, 1000, "140", "none", "mp4a"))
    snap = tracker.snapshot()
    assert snap.stage == "Downloading audio"
    assert snap.downloaded == 3500 and abs(snap.item_fraction - 0.875) < 1e-9
    tracker.feed("err", '@@gfgr:pp {"p":{"status":"started","postprocessor":"Merger"},"i":{"id":"x"}}')
    assert tracker.snapshot().stage == "Merging"
    tracker.feed("out", '@@gfgr:file {"id":"aaaaaaaaaaa","filepath":"C:/x.mp4"}')
    assert tracker.snapshot().overall == 1.0
    assert tracker.files == [{"id": "aaaaaaaaaaa", "filepath": "C:/x.mp4"}]


def test_a_part_without_a_listed_size_uses_the_running_estimate() -> None:
    """HLS formats list no size; the fragments' estimate keeps the bar moving instead of reading full."""
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"v","title":"Talk"}')
    tracker.feed("out", '@@gfgr:parts [{"format_id":"616","vcodec":"vp09","acodec":"none","filesize":null},'
                        '{"format_id":"140","vcodec":"none","acodec":"mp4a","filesize":1000}]')
    fractions = []
    for done, estimate, index in ((2000, 9000, 2), (4000, 9000, 4), (8000, 9000, 8)):
        tracker.feed("out", "@@gfgr:dl " + json.dumps({
            "p": {"status": "downloading", "downloaded_bytes": done, "total_bytes_estimate": estimate,
                  "fragment_index": index, "fragment_count": 9},
            "i": {"id": "v", "format_id": "616", "vcodec": "vp09", "acodec": "none"}}))
        snap = tracker.snapshot()
        assert snap.total == 10000  # the video's estimate and the audio's listed size
        fractions.append(snap.item_fraction)
    assert fractions == [0.2, 0.4, 0.8]
    # Without any size, the fragments done show the progress.
    bare = ProgressTracker()
    bare.feed("out", '@@gfgr:dl {"p":{"status":"downloading","downloaded_bytes":10,"fragment_index":3,'
                     '"fragment_count":12},"i":{"id":"v","format_id":"hls"}}')
    assert bare.snapshot().item_fraction == 0.25


def test_playlist_position_and_archive_skips() -> None:
    """Count items from yt-dlp's position lines, including ones the archive skips."""
    tracker = ProgressTracker()
    tracker.feed("out", "[download] Downloading item 1 of 4")
    tracker.feed("out", "[download] First has already been recorded in the archive")
    tracker.feed("out", "[download] Downloading item 2 of 4")
    tracker.feed("out", '@@gfgr:item {"id":"b","title":"Second"}')
    tracker.feed("out", dl(50, 100, "18", "avc1", "mp4a"))
    snap = tracker.snapshot()
    assert (snap.item_index, snap.item_count, snap.items_done, snap.archived) == (2, 4, 1, 1)
    assert abs(snap.overall - (1 + 0.5) / 4) < 1e-9
    assert tracker.archived_ids == []  # skipped by title: no ID to report
    tracker.feed("out", "[download] vsWerF0nuqM: has already been recorded in the archive")
    assert tracker.archived_ids == ["vsWerF0nuqM"] and tracker.snapshot().archived == 2


def test_live_and_waiting() -> None:
    """Show recording for live streams and the wait before a scheduled one."""
    tracker = ProgressTracker()
    tracker.feed("out", "[wait] Remaining time until next attempt: 01:02:03")
    assert tracker.snapshot().stage == "Waiting for the stream"
    assert tracker.snapshot().wait_seconds == 3723
    tracker.feed("out", '@@gfgr:item {"id":"l","title":"Live","live_status":"is_live"}')
    assert tracker.snapshot().stage == "Recording"


def test_audio_conversion_progress_comes_from_ffmpegs_file(tmp_path) -> None:
    """The conversion reports no progress through yt-dlp; ffmpeg's -progress file has it."""
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"s","title":"Song","duration":200}')
    tracker.feed("out", dl(900, 1000, "251", "none", "opus"))
    assert tracker.snapshot().speed > 0 and tracker.converting_since == 0
    tracker.feed("err", '@@gfgr:pp {"p":{"status":"started","postprocessor":"ExtractAudio"},"i":{"id":"s"}}')
    snap = tracker.snapshot()
    assert snap.stage == "Converting" and snap.duration == 200 and (snap.speed, snap.eta) == (0.0, -1)
    assert tracker.converting_since > 0
    progress = tmp_path / "convert.progress"
    assert read_convert_progress(progress, tracker.converting_since) is None  # not started yet
    progress.write_text("out_time_us=20000000\nspeed=8.0x\nprogress=continue\n"
                        "out_time_us=50000000\nspeed=10.0x\nprogress=continue\n", encoding="utf-8")
    assert read_convert_progress(progress, tracker.converting_since) == (50.0, 10.0)
    # The previous song's file, older than this conversion, isn't read as this one's.
    assert read_convert_progress(progress, tracker.converting_since + 60) is None
    tracker.feed("out", '@@gfgr:file {"id":"s","filepath":"C:/s.mp3"}')
    assert tracker.converting_since == 0
