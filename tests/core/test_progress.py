"""Output parsing and the progress snapshot."""

import json

from gfgmd.core.progress import ProgressTracker, parse_line


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


def test_live_and_waiting() -> None:
    """Show recording for live streams and the wait before a scheduled one."""
    tracker = ProgressTracker()
    tracker.feed("out", "[wait] Remaining time until next attempt: 01:02:03")
    assert tracker.snapshot().stage == "Waiting for the stream"
    assert tracker.snapshot().wait_seconds == 3723
    tracker.feed("out", '@@gfgr:item {"id":"l","title":"Live","live_status":"is_live"}')
    assert tracker.snapshot().stage == "Recording"
