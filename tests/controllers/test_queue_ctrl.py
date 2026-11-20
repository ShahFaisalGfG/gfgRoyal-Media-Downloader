"""The queue controller end to end with the fake yt-dlp: adding, running, finishing, and stopping."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers.queue_ctrl import QueueController
from gfgmd.controllers.queue_rows import entry_key, entry_row, job_key, running_values
from gfgmd.core import extract, naming
from gfgmd.core.naming import group_of
from gfgmd.core.extract import VideoProbe
from gfgmd.core.progress import Snapshot
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet
from gfgmd.services import recycle as recycle_module
from gfgmd.services.context import AppContext
from gfgmd.services.notifier import Notifier
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> AppContext:
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    settings = get_default_settings()
    settings["downloads"]["folder"] = str(tmp_path / "Downloads")
    settings["downloads"]["audio_folder"] = str(tmp_path / "Music")
    settings["notifications"]["enabled"] = False
    save_settings(settings)
    yield context
    context.close()


@pytest.fixture(autouse=True)
def fixed_quality():
    with patch.object(naming, "video_quality", return_value=720):
        yield


def fake_ffmpeg(command, on_line, stop):
    """Extract audio's ffmpeg run: progress, then the audio file."""
    on_line("out", "out_time_us=1000000")
    Path(command[-1]).write_bytes(b"audio")
    return 0, False


@pytest.fixture
def queue(qapp, context, fake_ytdlp):
    def runner(command, on_line, stop):
        if command[0] == TOOLS.ffmpeg:
            return fake_ffmpeg(command, on_line, stop)
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    notifier = Notifier(lambda: None, lambda path: None)
    notifier.attach(None)
    controller = QueueController(context, ToolManager(context), notifier, runner=runner)
    yield controller
    controller.shutdown()


def wait_for(qapp, condition, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def states(context: AppContext) -> list[str]:
    return [job["state"] for job in context.store.jobs()]


def test_download_finishes_and_reaches_the_library(qapp, queue, context):
    saved = []
    queue.fileSaved.connect(lambda history_id, path: saved.append(path))
    assert queue.addLinks("https://fake.test/ok", "video-best-mp4") == 1
    assert wait_for(qapp, lambda: states(context) == ["done"])
    assert wait_for(qapp, lambda: len(saved) == 1)
    assert saved[0].endswith("Clip (720p).mp4") and Path(saved[0]).exists()
    record = context.store.history()[0]
    assert record["filepath"] == saved[0] and record["kind"] == "video"
    row = queue.model.get(0)
    assert row["jobState"] == "done" and row["title"] == "Clip" and row["format"] == "MP4"
    assert queue.busy is False


def test_bad_links_are_reported_not_queued(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    assert queue.addLinks("not a link\nftp://x/y", "video-best-mp4") == 0
    assert context.store.jobs() == []
    assert notices and notices[0].startswith("4 links couldn't be added.")  # split at spaces and line breaks


def test_text_without_a_link_says_so_and_bare_links_get_https(qapp, queue, context):
    """Words copied by mistake read as "isn't a link"; "fake.test/ok" is taken as the link box takes it."""
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    assert queue.addLinks("just some words", "video-best-mp4") == 0
    assert notices[-1] == "The copied text isn't a link. Copy the link from your browser's address bar."
    assert queue.addLinks("fake.test/ok", "video-best-mp4") == 1
    assert context.store.jobs()[0]["url"] == "https://fake.test/ok"


def test_sign_in_needed_then_retry_after_sign_in(qapp, queue, context):
    sites = []
    queue.signInNeeded.connect(sites.append)
    queue.addLinks("https://fake.test/auth", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"])
    job = context.store.jobs()[0]
    assert job["action"] == "signin" and sites == [job["site"]]
    queue.retrySignIn(job["site"])
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"] and context.store.jobs()[0]["attempts"] == 1)


def test_full_disk_pauses_the_queue(qapp, queue, context):
    queue.addLinks("https://fake.test/disk", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["paused"])
    assert queue.paused is True
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    qapp.processEvents()
    assert states(context) == ["paused", "queued"]  # nothing starts while paused
    queue.resumeAll()
    assert wait_for(qapp, lambda: "done" in states(context))


def test_pause_resume_and_cancel_a_running_download(qapp, queue, context):
    queue.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    job_id = context.store.jobs()[0]["id"]
    queue.pause(job_id)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    queue.resume(job_id)
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    queue.cancel(job_id)
    assert wait_for(qapp, lambda: states(context) == ["cancelled"])


def test_a_stronger_stop_reason_is_kept(qapp):
    """Pause all after Cancel, or a restart after Pause, doesn't change what the download becomes."""
    from gfgmd.controllers.queue_ctrl import _Running
    running = _Running(1, "archive", "youtube", False)
    running.stop("cancel")
    running.stop("pause_all")
    running.stop("shutdown")
    assert running.stop_reason == "cancel"
    paused = _Running(2, "archive", "youtube", False)
    paused.stop("pause")
    paused.stop("restart")
    assert paused.stop_reason == "pause"
    paused.stop("remove")
    assert paused.stop_reason == "remove"


def test_quitting_keeps_a_paused_download_paused(qapp, context, fake_ytdlp):
    """A download paused just before the app quits is still paused at the next start, not queued."""
    controller = QueueController(context, ToolManager(context), Notifier(lambda: None, lambda path: None),
                                 runner=lambda c, o, s: run_to_completion(fake_ytdlp + c[1:], o, s))
    controller.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: controller.runningCount == 1)
    job_id = context.store.jobs()[0]["id"]
    controller.pause(job_id)
    controller.shutdown()
    assert context.store.job(job_id)["state"] == "paused"


def test_concurrency_limit_and_shared_archive(qapp, queue, context):
    settings = get_default_settings()
    settings["downloads"]["folder"] = str(Path(context.store.path).parent / "Downloads")
    settings["downloads"]["concurrent"] = 1
    save_settings(settings)
    queue.addLinks("https://fake.test/slow\nhttps://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    assert sorted(states(context)) == ["queued", "running"]
    queue.pauseAll()
    assert wait_for(qapp, lambda: queue.runningCount == 0)


def test_when_done_countdown(qapp, queue, context):
    countdowns = []
    queue.whenDoneCountdown.connect(countdowns.append)
    queue.setWhenDone("sleep")
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: countdowns == ["sleep"])
    queue.cancelWhenDone()
    assert queue.whenDone == "nothing"


def test_when_done_waits_while_a_download_is_paused(qapp, queue, context):
    """Pausing the last download (or Pause all) is not the queue finishing: no countdown."""
    countdowns = []
    queue.whenDoneCountdown.connect(countdowns.append)
    queue.setWhenDone("sleep")
    queue.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    job_id = context.store.jobs()[0]["id"]
    queue.pause(job_id)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    wait_for(qapp, lambda: bool(countdowns), timeout=1.5)
    assert countdowns == []
    queue.cancelWhenDone()


def test_downloads_that_needed_the_tools_try_again_once_updated(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    job_id = context.store.add_job("https://fake.test/ok", "generic", "https://fake.test/ok", "fake.test",
                                   {"kind": "video"}, str(Path(context.store.path).parent / "D"), state="failed")
    context.store.update_job(job_id, action="update_tools", error_key="extractor_broken")
    queue.retry_after_tools()
    assert context.store.job(job_id)["state"] == "queued" and context.store.job(job_id)["action"] == ""
    assert notices and "trying again" in notices[-1]


def test_quit_when_done_is_handed_to_the_app(qapp, queue):
    """Quit after the countdown asks the app to quit (past the window's close-to-tray), never the PC."""
    asked = []
    queue.quitRequested.connect(lambda: asked.append(True))
    queue.setWhenDone("quit")
    with patch("gfgmd.controllers.queue_ctrl.power.perform") as power:
        queue.performWhenDone()
    assert asked == [True] and not power.called and queue.whenDone == "nothing"


def test_download_again_keeps_the_files_type(qapp, queue, context):
    """A song downloaded again stays a song in its format, an MKV stays an MKV, whatever the preset."""
    queue.pauseAll()
    queue.download_again("https://fake.test/ok", "audio", "flac")
    queue.download_again("https://fake.test/flaky", "video", "mkv")
    song, video = (json.loads(job["options_json"]) for job in context.store.jobs())
    assert (song["kind"], song["audio_format"], song["ignore_archive"]) == ("audio", "flac", True)
    assert (video["kind"], video["container"]) == ("video", "mkv")


def test_interrupted_jobs_resume_on_start(qapp, context, fake_ytdlp):
    """They start at once, not at the queue's first tick 15 seconds later."""
    job_id = context.store.add_job("https://fake.test/ok", "generic", "https://fake.test/ok", "fake.test",
                                   {"kind": "video"}, str(Path(context.store.path).parent / "D"), state="running")
    notifier = Notifier(lambda: None, lambda path: None)
    controller = QueueController(context, ToolManager(context), notifier,
                                 runner=lambda c, o, s: run_to_completion(fake_ytdlp + c[1:], o, s))
    try:
        assert wait_for(qapp, lambda: context.store.job(job_id)["state"] == "done", timeout=8.0)
    finally:
        controller.shutdown()


def test_sign_in_copies_left_by_a_crash_are_removed_at_start(qapp, context):
    """Whatever a run left in the run folder (cookie copies above all) goes when the queue starts."""
    left = context.run_root / "7-1700000000"
    left.mkdir(parents=True)
    (left / "cookies.txt").write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    controller = QueueController(context, ToolManager(context), Notifier(lambda: None, lambda path: None))
    try:
        assert context.run_root.is_dir() and list(context.run_root.iterdir()) == []
    finally:
        controller.shutdown()


def test_move_and_remove(qapp, queue, context):
    queue.pauseAll()
    queue.addLinks("https://fake.test/ok\nhttps://fake.test/flaky", "audio-mp3")
    first, second = (job["id"] for job in context.store.jobs())
    assert json.loads(context.store.job(first)["options_json"])["kind"] == "audio"
    queue.move(second, -1)
    assert [job["id"] for job in context.store.jobs()] == [second, first]
    queue.remove(second, False)
    assert [job["id"] for job in context.store.jobs()] == [first]
    assert queue.model.count == 1


def _partials(context: AppContext) -> list[Path]:
    incomplete = Path(load_settings()["downloads"]["folder"]) / ".incomplete"
    return [entry for entry in incomplete.rglob("*.part")] if incomplete.is_dir() else []


def test_cancel_after_a_pause_deletes_the_unfinished_files(qapp, queue, context):
    queue.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1 and _partials(context))
    job_id = context.store.jobs()[0]["id"]
    queue.pause(job_id)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    assert _partials(context)  # a paused download keeps them to continue later
    queue.cancel(job_id)
    assert states(context) == ["cancelled"] and _partials(context) == []


def test_remove_with_files_sends_them_to_the_recycle_bin(qapp, queue, context):
    removed = []
    queue.filesRemoved.connect(lambda: removed.append(True))
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    job_id = context.store.jobs()[0]["id"]
    saved = context.store.history()[0]["filepath"]
    (context.job_dir(job_id) / "journal-marker").write_text("x", encoding="utf-8")
    with patch.object(recycle_module, "to_recycle_bin", return_value=False):
        queue.remove(job_id, True)
    assert states(context) == ["done"] and context.store.history()  # Windows refused: nothing changes
    with patch.object(recycle_module, "to_recycle_bin", return_value=True) as recycle:
        queue.remove(job_id, True)
    recycle.assert_called_once_with([saved])
    assert context.store.jobs() == [] and context.store.history() == [] and removed == [True]
    assert not context.job_dir(job_id).exists()  # a later job given the same id starts clean


def test_removing_a_running_download_with_files_deletes_its_unfinished_files(qapp, queue, context):
    queue.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1 and _partials(context))
    queue.remove(context.store.jobs()[0]["id"], True)
    assert wait_for(qapp, lambda: context.store.jobs() == [] and queue.runningCount == 0)
    assert _partials(context) == []


def test_extract_audio_of_a_finished_download(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    video_job = context.store.jobs()[0]["id"]
    probe = VideoProbe(duration=2.0, audio_stream=1, audio_codec="aac")
    with patch.object(extract, "probe_video", return_value=probe):
        queue.pauseAll()
        choices = {"audio_format": "flac", "embed_thumbnail": False, "lyrics": False, "kind": "video", "max_height": 0}
        queue.extractJobAudio(video_job, choices)
        queue.extractJobAudio(video_job, choices)  # a second press while it waits adds nothing
        assert len(context.store.jobs()) == 2 and notices[-1] == "Its audio is already being extracted."
        job = context.store.jobs()[1]
        options = json.loads(job["options_json"])
        assert (options["kind"], options["audio_format"], options["lyrics"]) == ("audio", "flac", False)
        assert job["input_path"] == context.store.history()[0]["filepath"] and job["title"] == "Clip"
        queue.resumeAll()
        assert wait_for(qapp, lambda: states(context) == ["done", "done"] and len(context.store.history()) == 2)
    song = Path(context.store.history()[0]["filepath"])
    assert song.name == "Clip.flac" and song.is_file() and song.is_relative_to(Path(load_settings()["downloads"]["audio_folder"]))
    assert context.store.history()[0]["kind"] == "audio"
    row = queue.model.get(1)
    assert row["kind"] == "audio" and row["lastFile"] == str(song)


def test_the_same_video_again_plays_the_file_already_downloaded(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    assert queue.addLinks("https://fake.test/ok", "video-best-mp4") == 1
    # The same link with the same choices while it waits: nothing more is queued.
    assert queue.addLinks("https://fake.test/ok", "video-best-mp4") == 1
    assert len(context.store.jobs()) == 1 and notices[-1] == "Already in the list with the same choices."
    queue.resumeAll()
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first = context.store.history()[0]["filepath"]
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done", "done"])
    again = context.store.jobs()[1]
    assert again["message"] == "Already downloaded" and again["title"] == "Clip"
    assert queue.model.get(1)["lastFile"] == first and len(context.store.history()) == 1
    # Download again ignores the archive and saves a second copy.
    assert queue.model.get(1)["canRedownload"] is True
    queue.downloadAgain(again["id"])
    assert wait_for(qapp, lambda: states(context) == ["done", "done"] and len(context.store.history()) == 2)
    assert context.store.job(again["id"])["message"] == "1 video saved"
    # Try again goes back to the archive's rule.
    queue.retry(again["id"])
    assert wait_for(qapp, lambda: context.store.job(again["id"])["message"] == "Already downloaded")


def test_a_video_whose_file_is_gone_downloads_again(qapp, queue, context):
    """Deleted after downloading (in Explorer, or with its library record): asking again downloads it."""
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first = Path(context.store.history()[0]["filepath"])
    first.unlink()
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done", "done"] and first.exists())
    again = context.store.jobs()[1]
    assert again["message"] == "1 video saved" and queue.model.get(1)["lastFile"] == str(first)
    # The file took its old name back, so its library record is the new download's.
    assert [record["job_id"] for record in context.store.history()] == [again["id"]]


def test_the_list_shows_how_far_a_conversion_has_got():
    """Converting shows its own share done and time left, not the finished download's speed."""
    snap = Snapshot(stage="Converting to MP3", downloaded=12_000_000, total=12_000_000, convert_fraction=0.45,
                    eta=10, overall=0.999, item_count=1, phase="post")
    values = running_values(snap)
    assert values["progress"] == 0.45 and values["statusText"] == "Converting to MP3"
    assert values["detail"] == "45%  ·  11.4 MB downloaded  ·  about 10 seconds left"
    # Without ffmpeg's progress (merging, or a conversion not started yet) the bar sweeps.
    merging = Snapshot(stage="Putting the video together", downloaded=5, speed=900.0, phase="post")
    assert running_values(merging)["progress"] == -1.0 and "/s" not in running_values(merging)["detail"]


def test_finished_downloads_leave_the_list_when_the_app_closes(qapp, context, fake_ytdlp):
    """The Library keeps finished files; the list keeps what still needs doing."""
    def make():
        return QueueController(context, ToolManager(context), Notifier(lambda: None, lambda path: None),
                               runner=lambda c, o, s: run_to_completion(fake_ytdlp + c[1:], o, s))
    first = make()
    first.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first.addLinks("https://fake.test/auth", "audio-mp3")
    assert wait_for(qapp, lambda: states(context) == ["done", "needs_auth"])
    first.pauseAll()
    first.addLinks("https://fake.test/slow", "video-best-mp4")
    first.shutdown()
    assert states(context) == ["needs_auth", "queued"] and len(context.store.history()) == 1
    # Kept when Preferences says so, and cleared at the next start otherwise (after a crash, say).
    settings = load_settings()
    settings["downloads"]["clear_finished_on_exit"] = False
    save_settings(settings)
    finished = context.store.add_job("https://fake.test/x", "generic", "x", "fake.test", {"kind": "video"},
                                     settings["downloads"]["folder"], state="done")
    second = make()
    second.shutdown()
    assert context.store.job(finished) is not None
    settings["downloads"]["clear_finished_on_exit"] = True
    save_settings(settings)
    third = make()
    try:
        assert context.store.job(finished) is None and third.model.count == 2
    finally:
        third.shutdown()


def test_removing_always_deletes_unfinished_parts_and_asks_only_when_needed(qapp, queue, context):
    """A paused download's parts go with it; saved files stay unless asked; the page asks only to lose work."""
    queue.addLinks("https://fake.test/slow", "video-best-mp4")
    assert wait_for(qapp, lambda: queue.runningCount == 1 and _partials(context))
    slow = context.store.jobs()[0]["id"]
    assert queue.removal([slow]) == {"count": 1, "inProgress": 1, "savedFiles": 0}
    queue.pause(slow)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    assert queue.removal([slow]) == {"count": 1, "inProgress": 1, "savedFiles": 0}  # paused is still to finish
    queue.remove(slow, False)
    assert context.store.jobs() == [] and _partials(context) == []
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    done = context.store.jobs()[0]["id"]
    assert queue.removal([done]) == {"count": 1, "inProgress": 0, "savedFiles": 1}
    queue.remove(done, False)
    assert context.store.jobs() == [] and Path(context.store.history()[0]["filepath"]).exists()
    queue.pauseAll()
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    waiting = context.store.jobs()[0]["id"]
    queue.cancel(waiting)
    assert queue.removal([waiting]) == {"count": 1, "inProgress": 0, "savedFiles": 0}  # removed without asking


def test_actions_on_several_downloads_at_once(qapp, queue, context):
    """One refresh and one Recycle Bin notice for the lot; removal() adds up what would be lost."""
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    queue.addLinks("https://fake.test/ok https://fake.test/playlist", "video-best-mp4")
    ids = [job["id"] for job in context.store.jobs()]
    changes = []
    queue.changed.connect(lambda: changes.append(True))
    queue.applyToJobs("pause", ids)
    assert states(context) == ["paused", "paused"] and len(changes) == 1
    assert queue.removal(ids) == {"count": 2, "inProgress": 2, "savedFiles": 0}
    queue.applyToJobs("resume", ids)
    queue.resumeAll()
    assert wait_for(qapp, lambda: states(context) == ["done", "done"] and len(context.store.history()) == 3)
    assert queue.removal(ids) == {"count": 2, "inProgress": 0, "savedFiles": 3}
    with patch.object(recycle_module, "to_recycle_bin", return_value=True):
        queue.applyToJobs("remove_saved", ids)
    assert context.store.jobs() == [] and context.store.history() == []
    assert notices[-1] == "Moved 3 files to the Recycle Bin."
    queue.applyToJobs("unknown", ids)  # ignored


def test_extract_audio_of_several_library_files_leaves_songs_out(qapp, queue, context, tmp_path):
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    song = tmp_path / "Song.mp3"
    song.write_bytes(b"a")
    song_id = context.store.add_history(str(song), title="Song", kind="audio")
    queue.extractAudio([song_id], {})
    assert context.store.jobs() == [] and notices[-1].startswith("Only videos have audio")
    video = tmp_path / "Clip (720p).mp4"
    video.write_bytes(b"v")
    video_id = context.store.add_history(str(video), title="Clip", kind="video")
    queue.extractAudio([song_id, video_id], {"audio_format": "flac"})
    jobs = context.store.jobs()
    assert [job["input_path"] for job in jobs] == [str(video)]



# ── Playlists in the list ──

def rows_of(queue) -> list[dict]:
    return [queue.model.get(i) for i in range(queue.model.count)]


def test_a_playlist_shows_its_videos_and_each_lands_in_the_library(qapp, queue, context):
    saved = []
    queue.fileSaved.connect(lambda history_id, path: saved.append(path))
    queue.addLinks("https://fake.test/listed", "video-best-mp4")
    assert wait_for(qapp, lambda: states(context) == ["done"] and len(saved) == 3)
    job = context.store.jobs()[0]
    rows = rows_of(queue)
    assert [row["rowType"] for row in rows] == ["job", "entry", "entry", "entry"]
    assert rows[0]["entryCount"] == 3 and rows[0]["expanded"] is True and rows[0]["detail"] == "3 videos saved"
    assert [(row["number"], row["title"], row["statusText"]) for row in rows[1:]] == [
        (1, "First", "Saved"), (2, "Second", "Saved"), (3, "Third", "Saved")]
    assert rows[1]["lastFile"] == saved[0] and rows[1]["thumbnail"].endswith("/aaaaaaaaaaa/hq.jpg")
    records = sorted(context.store.history(), key=lambda record: record["position"])
    assert [record["position"] for record in records] == [1, 2, 3]
    assert {record["group_title"] for record in records} == {"Fake List"}
    assert queue.savedFiles(job["id"]) == [row["lastFile"] for row in rows[1:]]  # Play's order
    queue.setExpanded(job["id"], False)
    assert [row["rowType"] for row in rows_of(queue)] == ["job"]


def test_a_stalled_video_waits_while_the_rest_download(qapp, context, fake_ytdlp):
    def runner(command, on_line, stop):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    notifier = Notifier(lambda: None, lambda path: None)
    notifier.attach(None)
    queue = QueueController(context, ToolManager(context), notifier, runner=runner, stall_seconds=1.0)
    try:
        queue.addLinks("https://fake.test/stall", "video-best-mp4")
        job_id = context.store.jobs()[0]["id"]
        assert wait_for(qapp, lambda: states(context) == ["done"])
        assert context.store.item_counts(job_id) == {"done": 3}
        assert queue.model.get(queue.model.row_of(job_key(job_id)))["progress"] == 1.0
        # The stalled video was saved after the rest. Its "deferred" state can come and go between two
        # polls, so the order of the saved files is what shows it waited.
        saved = [record["video_id"] for record in sorted(context.store.history_for_job(job_id), key=lambda r: r["id"])]
        assert saved == ["aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"]
    finally:
        queue.shutdown()


def test_a_video_set_aside_says_it_waits_for_its_server():
    job = {"id": 1, "state": "running", "options_json": "{}"}
    item = {"item_id": "bbbbbbbbbbb", "state": "deferred", "title": "Clip", "url": "", "thumbnail": "", "message": ""}
    assert entry_row(job, item, 2, "video", "", None)["statusText"] == "Waiting for its server"


def test_a_subscriptions_new_uploads_are_one_download(qapp, queue, context):
    from gfgmd.core.sources import source_from_url
    queue.pauseAll()
    source = source_from_url("https://www.youtube.com/playlist?list=PLabcdefghijklmnop")
    uploads = [{"id": video_id, "title": f"Upload {video_id[:3]}", "url": f"https://fake.test/batch/{video_id}",
                "thumbnail": ""} for video_id in ("aaaaaaaaaaa", "bbbbbbbbbbb")]
    options = queue._preset_options("video-best-mp4")
    assert queue.add_subscription_items(uploads, source, options, 1, None, title="Mix", url="https://youtu.be/mix",
                                        folder="Mix: Best of") == 2
    job = context.store.jobs()[0]
    assert (job["title"], job["batch"], job["folder"], job["items_total"]) == ("Mix: 2 videos", 1, "Mix: Best of", 2)
    queue.resumeAll()
    assert wait_for(qapp, lambda: states(context) == ["done"])
    assert {Path(record["filepath"]).parent.name for record in context.store.history()} == {"Mix_ Best of"}
    assert context.store.item_counts(job["id"]) == {"done": 2}


def test_picked_flags_say_what_the_selection_allows(qapp, queue, context):
    queue.pauseAll()
    queue.addLinks("https://fake.test/ok", "video-best-mp4")
    job_id = context.store.jobs()[0]["id"]
    assert queue.pickedFlags([job_id]) == {"canPause": True, "canResume": False, "canRetry": False}
    queue.pause(job_id)
    assert queue.pickedFlags([job_id]) == {"canPause": False, "canResume": True, "canRetry": False}


def test_files_are_grouped_by_their_playlist_folder(tmp_path):
    root = tmp_path / "Videos"
    assert group_of(root / "Clip.mp4", root) == ("", "")
    key, title = group_of(root / "Channel" / "Videos" / "Clip.mp4", root)
    assert key == str(root / "Channel" / "Videos").casefold() and title == "Channel · Videos"
    assert group_of(tmp_path / "Elsewhere" / "Clip.mp4", root) == ("", "")
