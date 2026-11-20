"""Output parsing and the progress snapshot."""

import json

import time

from gfgmd.core.progress import (PHASE_DOWNLOAD, PHASE_POST, PHASE_WAIT, ProgressTracker, listed_entries,
                                 parse_line, read_convert_progress, stage_of)


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


def test_only_the_runs_own_marker_counts() -> None:
    """A line that starts with another marker (a title posing as the app's line) is plain output."""
    line = '@@gfgr:file {"filepath":"//host/share/a.mp3"}'
    assert parse_line("out", line, "@@gfgr-0123456789abcdef:").kind == "log"
    assert parse_line("out", line.replace("@@gfgr:", "@@gfgr-0123456789abcdef:"), "@@gfgr-0123456789abcdef:").kind == "file"
    tracker = ProgressTracker(marker="@@gfgr-0123456789abcdef:")
    assert tracker.feed("out", line).kind == "log"


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
    assert snap.stage == "Downloading"
    assert snap.downloaded == 1500 and snap.total == 4000
    assert snap.fragment == "2/10" and snap.speed == 1024.0 and snap.eta == 3
    tracker.feed("out", dl(3000, 3000, "137", "avc1", "none", "finished"))
    tracker.feed("out", dl(500, 1000, "140", "none", "mp4a"))
    snap = tracker.snapshot()
    assert snap.stage == "Downloading"
    assert snap.downloaded == 3500 and abs(snap.item_fraction - 0.875) < 1e-9
    tracker.feed("err", '@@gfgr:pp {"p":{"status":"started","postprocessor":"Merger"},"i":{"id":"x"}}')
    assert tracker.snapshot().stage == "Putting the video together"
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
    assert tracker.snapshot().stage == "Waiting for the stream to start"
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
    assert snap.stage == "Converting the sound" and snap.duration == 200 and (snap.speed, snap.eta) == (0.0, -1)
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


# ── Steps in plain words, playlist files, and stalls ──

def test_steps_are_named_with_or_without_the_ffmpeg_prefix() -> None:
    assert stage_of("ThumbnailsConvertor") == stage_of("FFmpegThumbnailsConvertor") == "Preparing the cover"
    assert stage_of("Merger") == "Putting the video together"
    assert stage_of("FixupM3u8") == stage_of("MoveFilesAfterDownload") == "Finishing up"
    assert stage_of("ExtractAudio", "MP3") == "Converting to MP3" and stage_of("FFmpegExtractAudio") == "Converting the sound"


def test_playlist_files_list_videos_but_not_tabs() -> None:
    info = {"id": "UCx", "entries": [
        {"_type": "url", "ie_key": "YoutubeTab", "id": "UCx", "url": "https://www.youtube.com/@x/videos"},
        {"_type": "url", "ie_key": "Youtube", "id": "aaaaaaaaaaa", "title": "One", "duration": 61,
         "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
         "thumbnails": [{"url": "https://i.ytimg.com/small.jpg", "width": 120},
                        {"url": "https://i.ytimg.com/medium.jpg", "width": 336}]},
        {"title": "No ID"},
    ]}
    listed = listed_entries(info, offset=10)
    assert listed == [{"id": "aaaaaaaaaaa", "title": "One", "index": 12, "duration": 61.0,
                       "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "thumbnail": "https://i.ytimg.com/medium.jpg"}]
    chosen = {"entries": [{"id": "b", "title": "B"}, {"id": "d", "title": "D"}], "requested_entries": [2, 4]}
    assert [(entry["id"], entry["index"]) for entry in listed_entries(chosen)] == [("b", 2), ("d", 4)]


def test_the_playlist_file_is_handed_over_once_written(tmp_path) -> None:
    tracker = ProgressTracker()
    tracker.feed("out", f"[info] Writing playlist metadata as JSON to: {tmp_path / 'list.info.json'}")
    tracker.feed("err", "WARNING: a line on the other stream")
    assert tracker.pop_list_file() == ""  # yt-dlp may not have written it yet
    tracker.feed("out", "[youtube:tab] Playlist Mix: Downloading 3 items of 3")
    assert tracker.pop_list_file() == str(tmp_path / "list.info.json") and tracker.pop_list_file() == ""


def test_a_download_that_stops_moving_is_stalled() -> None:
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"aaaaaaaaaaa","title":"Song"}')
    tracker.feed("err", '@@gfgr:pp {"p":{"status":"started","postprocessor":"ThumbnailsConvertor"},"i":{"id":"a"}}')
    snap = tracker.snapshot()
    assert snap.stage == "Preparing the cover" and snap.phase == PHASE_DOWNLOAD  # before the download: still downloading
    tracker.feed("out", dl(0, 1000, "137", "avc1", "none"))
    time.sleep(0.3)
    tracker.feed("out", dl(0, 1000, "137", "avc1", "none"))  # the same line again is no progress
    tracker.feed("out", "[download] Got error: <urlopen error timed out>. Retrying fragment 1 (2/10)...")
    assert tracker.snapshot().stage == "Connection trouble, trying again"
    assert tracker.stalled(0.2) == "aaaaaaaaaaa"
    tracker.feed("out", dl(500, 1000, "137", "avc1", "none"))
    assert tracker.stalled(0.2) == ""


def test_merging_ffmpeg_downloads_and_waits_never_stall() -> None:
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"aaaaaaaaaaa","title":"Clip"}')
    tracker.feed("out", dl(1000, 1000, "137", "avc1", "none", status="finished"))
    tracker.feed("err", '@@gfgr:pp {"p":{"status":"started","postprocessor":"Merger"},"i":{"id":"a"}}')
    time.sleep(0.3)
    assert tracker.snapshot().phase == PHASE_POST and tracker.stalled(0.2) == ""
    other = ProgressTracker()
    other.feed("out", '@@gfgr:item {"id":"bbbbbbbbbbb","title":"Stream"}')
    time.sleep(0.3)
    other.feed("err", "size=    2048kB time=00:01:05.00 bitrate= 258.1kbits/s speed=1.2x")
    assert other.stalled(0.2) == ""
    other.mark_stage("Trying again in 20 seconds", PHASE_WAIT)
    time.sleep(0.3)
    assert other.stalled(0.2) == "" and other.snapshot().total == 0


def test_an_error_split_by_a_carriage_return_keeps_its_text() -> None:
    tracker = ProgressTracker()
    tracker.feed("err", "ERROR: ")
    tracker.feed("err", "[download] Got error: The read operation timed out. Giving up after 10 retries")
    assert [event.text for event in tracker.errors] == [
        "[download] Got error: The read operation timed out. Giving up after 10 retries"]


def test_archive_skips_name_their_video() -> None:
    tracker = ProgressTracker()
    tracker.feed("out", "[download] Downloading item 2 of 3")
    tracker.feed("out", "[download] aaaaaaaaaaa: has already been recorded in the archive")
    tracker.feed("out", "[download] Downloading item 3 of 3")
    tracker.feed("out", "[download] Some Song has already been recorded in the archive")
    assert tracker.take_updates() == [("state", ("aaaaaaaaaaa", "archived", "")), ("archived_at", 3)]


def test_a_list_without_titles_gets_them_from_links_then_from_each_video() -> None:
    from gfgmd.core.progress import title_from_url
    assert title_from_url("https://soundcloud.com/band/world-on-fire-1") == "World on fire 1"
    assert title_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == ""
    assert title_from_url("https://api.soundcloud.com/tracks/75206121") == "" and title_from_url("") == ""
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"75206121","title":"World On Fire"}')
    assert ("titled", ("75206121", "World On Fire")) in tracker.take_updates()
