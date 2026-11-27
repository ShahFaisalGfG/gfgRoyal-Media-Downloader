"""The queue controller end to end with the fake yt-dlp: adding, running, finishing, and stopping."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers.queue_ctrl import QueueController, base_options
from gfgmd.controllers.queue_rows import entry_row, job_key, running_values
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

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno", gallery_dl="FAKE-GALLERY-DL")


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> AppContext:
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    settings = get_default_settings()
    settings["downloads"]["folder"] = str(tmp_path / "Downloads")
    settings["downloads"]["audio_folder"] = str(tmp_path / "Music")
    settings["downloads"]["photo_folder"] = str(tmp_path / "Pictures")
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
def queue(qapp, context, fake_ytdlp, fake_gallerydl):
    def runner(command, on_line, stop):
        if command[0] == TOOLS.ffmpeg:
            return fake_ffmpeg(command, on_line, stop)
        if command[0] == TOOLS.gallery_dl:
            return run_to_completion(fake_gallerydl + command[1:], on_line, stop)
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
    assert queue.addLinks("https://fake.test/ok", "video") == 1
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
    assert queue.addLinks("not a link\nftp://x/y", "video") == 0
    assert context.store.jobs() == []
    assert notices and notices[0].startswith("4 links couldn't be added.")  # split at spaces and line breaks


def test_text_without_a_link_says_so_and_bare_links_get_https(qapp, queue, context):
    """Words copied by mistake read as "isn't a link"; "fake.test/ok" is taken as the link box takes it."""
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    assert queue.addLinks("just some words", "video") == 0
    assert notices[-1] == "The copied text isn't a link. Copy the link from your browser's address bar."
    assert queue.addLinks("fake.test/ok", "video") == 1
    assert context.store.jobs()[0]["url"] == "https://fake.test/ok"


def test_sign_in_needed_then_retry_after_sign_in(qapp, queue, context):
    sites = []
    queue.signInNeeded.connect(sites.append)
    queue.addLinks("https://fake.test/auth", "video")
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"])
    job = context.store.jobs()[0]
    assert job["action"] == "signin" and sites == [job["site"]]
    queue.retrySignIn(job["site"])
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"] and context.store.jobs()[0]["attempts"] == 1)


def test_yt_dlp_errors_reach_the_log(qapp, queue, context):
    """yt-dlp's own words for a failure go to the log (written when logging is on); the row says it plainly."""
    lines: list[tuple[str, str]] = []

    def logged(message: str, level: str = "general") -> None:
        lines.append((message, level))
    with patch("gfgmd.controllers.queue_ctrl.write_log", logged):
        queue.addLinks("https://fake.test/private", "video")
        assert wait_for(qapp, lambda: states(context) == ["failed"])
    prefix = f"Download {context.store.jobs()[0]['id']}: "
    assert any(level == "critical" and message.startswith(prefix) and "Private video" in message
               for message, level in lines)


def test_a_finished_download_deletes_its_saved_videos_leftovers(qapp, queue, context):
    """A part an earlier attempt left of a video since saved (another stream) goes when the download
    finishes; a skipped video's part stays for Try again until the download leaves the list, and the
    emptied folder goes with it."""
    queue.pauseAll()
    queue.addLinks("https://fake.test/playlist", "video")
    job = context.store.jobs()[0]
    context.store.add_items(job["id"], [{"id": video_id, "title": title, "index": number} for number, (video_id, title)
                                        in enumerate((("aaaaaaaaaaa", "First"), ("bbbbbbbbbbb", "Second"),
                                                      ("ccccccccccc", "Third")), start=1)])
    folder = Path(job["output_root"]) / ".incomplete" / "Fake List"
    folder.mkdir(parents=True)
    saved_part = folder / "First [aaaaaaaaaaa] (requested-best).mp4.part"
    skipped_part = folder / "Second [bbbbbbbbbbb] (requested-best).mp4.part"
    for part in (saved_part, saved_part.with_suffix(".ytdl"), skipped_part):
        part.write_bytes(b"part")
    queue._keep_partials(job["id"], {str(saved_part), str(skipped_part)})
    queue.resumeAll()
    assert wait_for(qapp, lambda: states(context) == ["done"])
    assert sorted(path.name for path in folder.iterdir()) == [skipped_part.name]
    queue.clearFinished()
    assert not folder.exists() and folder.parent.is_dir()


def test_full_disk_pauses_the_queue(qapp, queue, context):
    queue.addLinks("https://fake.test/disk", "video")
    assert wait_for(qapp, lambda: states(context) == ["paused"])
    assert queue.paused is True
    queue.addLinks("https://fake.test/ok", "video")
    qapp.processEvents()
    assert states(context) == ["paused", "queued"]  # nothing starts while paused
    queue.resumeAll()
    assert wait_for(qapp, lambda: "done" in states(context))


def test_pause_resume_and_cancel_a_running_download(qapp, queue, context):
    """Cancel and delete unfinished files takes the download off the list once it stops."""
    queue.addLinks("https://fake.test/slow", "video")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    job_id = context.store.jobs()[0]["id"]
    queue.pause(job_id)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    queue.resume(job_id)
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    queue.remove(job_id, False)
    assert wait_for(qapp, lambda: context.store.jobs() == [] and queue.runningCount == 0)


def test_a_stronger_stop_reason_is_kept(qapp):
    """Pause all after Remove, or a restart after Pause, doesn't change what the download becomes."""
    from gfgmd.controllers.queue_ctrl import _Running
    running = _Running(1, "archive", "youtube", False)
    running.stop("remove")
    running.stop("pause_all")
    running.stop("shutdown")
    assert running.stop_reason == "remove"
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
    controller.addLinks("https://fake.test/slow", "video")
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
    queue.addLinks("https://fake.test/slow\nhttps://fake.test/ok", "video")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    assert sorted(states(context)) == ["queued", "running"]
    queue.pauseAll()
    assert wait_for(qapp, lambda: queue.runningCount == 0)


def test_when_done_countdown(qapp, queue, context):
    countdowns = []
    queue.whenDoneCountdown.connect(countdowns.append)
    queue.setWhenDone("sleep")
    queue.addLinks("https://fake.test/ok", "video")
    assert wait_for(qapp, lambda: countdowns == ["sleep"])
    queue.cancelWhenDone()
    assert queue.whenDone == "nothing"


def test_when_done_waits_while_a_download_is_paused(qapp, queue, context):
    """Pausing the last download (or Pause all) is not the queue finishing: no countdown."""
    countdowns = []
    queue.whenDoneCountdown.connect(countdowns.append)
    queue.setWhenDone("sleep")
    queue.addLinks("https://fake.test/slow", "video")
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
    """A song downloaded again stays a song in its format, an MKV stays an MKV, whatever the switch says."""
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
    queue.addLinks("https://fake.test/ok\nhttps://fake.test/flaky", "audio")
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


def test_remove_with_files_sends_them_to_the_recycle_bin(qapp, queue, context):
    removed = []
    queue.filesRemoved.connect(lambda: removed.append(True))
    queue.addLinks("https://fake.test/ok", "video")
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


def _moved_out(paths: list[str]) -> bool:
    """Windows moving files to the Recycle Bin, as far as their folder sees it."""
    for path in paths:
        Path(path).unlink()
    return True


def test_removing_a_playlist_with_its_files_removes_its_emptied_folder(qapp, queue, context):
    """The playlist's folder goes with its last file and the download folder stays; yt-dlp's emptied
    folder in .incomplete went when the download finished."""
    queue.addLinks("https://fake.test/listed", "video")
    assert wait_for(qapp, lambda: states(context) == ["done"] and len(context.store.history()) == 3)
    root = Path(load_settings()["downloads"]["folder"])
    folder = root / "Fake List"
    assert folder.is_dir() and not (root / ".incomplete" / "Fake List").exists()
    assert {record["output_root"] for record in context.store.history()} == {str(root)}
    with patch.object(recycle_module, "to_recycle_bin", side_effect=_moved_out):
        queue.remove(context.store.jobs()[0]["id"], True)
    assert context.store.history() == [] and not folder.exists() and root.is_dir()


def test_emptied_scratch_folders_stay_while_another_download_there_runs(qapp, queue, context):
    """Another download into the same folder may have just made its folder in .incomplete."""
    from gfgmd.controllers.queue_ctrl import _Running
    root = load_settings()["downloads"]["folder"]
    left = Path(root) / ".incomplete" / "Fake List"
    left.mkdir(parents=True)
    queue._running[99] = _Running(99, "archive", "youtube", False, root)
    queue._tidy_scratch(root)
    assert left.is_dir()
    del queue._running[99]
    queue._tidy_scratch(root)
    assert not left.exists() and left.parent.is_dir()


def test_the_pc_stays_awake_while_downloading_unless_turned_off(qapp, queue, context):
    """On while a download runs, off once nothing does, and off straight away when the setting is."""
    calls: list[bool] = []
    settings = load_settings()
    with patch("gfgmd.controllers.queue_ctrl.power.keep_awake", side_effect=calls.append):
        queue.addLinks("https://fake.test/slow", "video")
        assert wait_for(qapp, lambda: calls == [True])
        settings["downloads"]["keep_awake"] = False
        save_settings(settings)
        assert wait_for(qapp, lambda: calls == [True, False])
        settings["downloads"]["keep_awake"] = True
        save_settings(settings)
        assert wait_for(qapp, lambda: calls == [True, False, True])
        queue.remove(context.store.jobs()[0]["id"], False)
        assert wait_for(qapp, lambda: queue.runningCount == 0 and calls == [True, False, True, False])


def test_removing_a_running_download_with_files_deletes_its_unfinished_files(qapp, queue, context):
    queue.addLinks("https://fake.test/slow", "video")
    assert wait_for(qapp, lambda: queue.runningCount == 1 and _partials(context))
    queue.remove(context.store.jobs()[0]["id"], True)
    assert wait_for(qapp, lambda: context.store.jobs() == [] and queue.runningCount == 0)
    assert _partials(context) == []


def test_extract_audio_of_a_finished_download(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    queue.addLinks("https://fake.test/ok", "video")
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
    assert queue.addLinks("https://fake.test/ok", "video") == 1
    # The same link with the same choices while it waits: nothing more is queued.
    assert queue.addLinks("https://fake.test/ok", "video") == 1
    assert len(context.store.jobs()) == 1 and notices[-1] == "Already in the list with the same choices."
    queue.resumeAll()
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first = context.store.history()[0]["filepath"]
    queue.addLinks("https://fake.test/ok", "video")
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
    queue.addLinks("https://fake.test/ok", "video")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first = Path(context.store.history()[0]["filepath"])
    first.unlink()
    queue.addLinks("https://fake.test/ok", "video")
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
    first.addLinks("https://fake.test/ok", "video")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    first.addLinks("https://fake.test/auth", "audio")
    assert wait_for(qapp, lambda: states(context) == ["done", "needs_auth"])
    first.pauseAll()
    first.addLinks("https://fake.test/slow", "video")
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
    queue.addLinks("https://fake.test/slow", "video")
    assert wait_for(qapp, lambda: queue.runningCount == 1 and _partials(context))
    slow = context.store.jobs()[0]["id"]
    assert queue.removal([slow]) == {"count": 1, "inProgress": 1, "savedFiles": 0}
    queue.pause(slow)
    assert wait_for(qapp, lambda: states(context) == ["paused"] and queue.runningCount == 0)
    assert queue.removal([slow]) == {"count": 1, "inProgress": 1, "savedFiles": 0}  # paused is still to finish
    assert _partials(context)  # a paused download keeps them to continue later
    queue.remove(slow, False)
    assert context.store.jobs() == [] and _partials(context) == []
    queue.addLinks("https://fake.test/ok", "video")
    assert wait_for(qapp, lambda: states(context) == ["done"] and context.store.history())
    done = context.store.jobs()[0]["id"]
    assert queue.removal([done]) == {"count": 1, "inProgress": 0, "savedFiles": 1}
    queue.remove(done, False)
    assert context.store.jobs() == [] and Path(context.store.history()[0]["filepath"]).exists()


def test_actions_on_several_downloads_at_once(qapp, queue, context):
    """One refresh and one Recycle Bin notice for the lot; removal() adds up what would be lost."""
    notices = []
    queue.notice.connect(notices.append)
    queue.pauseAll()
    queue.addLinks("https://fake.test/ok https://fake.test/playlist", "video")
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


def test_deleting_a_video_stops_extracting_its_audio_first(qapp, context, fake_ytdlp, tmp_path):
    """FFmpeg reading the video would keep Windows from moving it, so the extraction is stopped, taken
    off the list, and waited for before the players let go."""
    reading = threading.Event()

    def runner(command, on_line, stop):
        if command[0] == TOOLS.ffmpeg:
            reading.set()
            stop.wait(10)
            return 1, True
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)

    notifier = Notifier(lambda: None, lambda path: None)
    notifier.attach(None)
    released: list[list[str]] = []
    queue = QueueController(context, ToolManager(context), notifier, runner=runner, release_player=released.append)
    video = tmp_path / "Clip (720p).mp4"
    video.write_bytes(b"v")
    video_id = context.store.add_history(str(video), title="Clip", kind="video")
    probe = VideoProbe(duration=2.0, audio_stream=1, audio_codec="aac")
    with patch.object(extract, "probe_video", return_value=probe):
        queue.extractAudio([video_id], {"audio_format": "flac", "embed_thumbnail": False, "lyrics": False})
        assert wait_for(qapp, reading.is_set)
        queue.release_files([str(video)])
    assert context.store.jobs() == [] and released == [[str(video)]]
    queue.shutdown()


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
    queue.addLinks("https://fake.test/listed", "video")
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
        queue.addLinks("https://fake.test/stall", "video")
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


def test_videos_its_archive_records_show_as_downloaded_before(qapp, queue, context):
    """A list's videos still waiting when it ends, but in its archive, read "Downloaded before"."""
    from gfgmd.core.jobs import JobResult
    queue.pauseAll()
    queue.addLinks("https://fake.test/playlist", "video")
    job = context.store.jobs()[0]
    context.store.add_items(job["id"], [{"id": "aaaaaaaaaaa", "title": "First", "index": 1},
                                        {"id": "bbbbbbbbbbb", "title": "Second", "index": 2}])
    archive = Path(queue._job_archive(job))
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("youtube aaaaaaaaaaa\n", encoding="utf-8")
    queue._record_result(context.store.job(job["id"]), JobResult("done", archived=1, kind="video"))
    states_by_id = {item["item_id"]: item["state"] for item in context.store.job_items(job["id"])}
    assert states_by_id == {"aaaaaaaaaaa": "archived", "bbbbbbbbbbb": "pending"}


def test_a_wait_to_try_again_says_why():
    from gfgmd.core.progress import PHASE_WAIT
    snap = Snapshot(stage="Trying again in 5 minutes", phase=PHASE_WAIT, reason="The connection dropped")
    assert running_values(snap)["detail"] == "The connection dropped"


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
    options = base_options(load_settings(), "video")
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
    queue.addLinks("https://fake.test/ok", "video")
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


# ── A video inside a playlist, and Smart Mode ──

IN_LIST = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghijklmnop"


def test_a_video_inside_a_playlist_waits_for_the_answer(qapp, queue, context):
    """Other links queue at once; the answer decides, and remembering it skips the question next time."""
    queue.pauseAll()
    asked = []
    queue.playlistQuestion.connect(asked.append)
    assert queue.addLinks(f"https://fake.test/ok\n{IN_LIST}", "video") == 2
    assert asked == [1] and [job["url"] for job in context.store.jobs()] == ["https://fake.test/ok"]
    queue.answerPlaylist("video", False)
    job = context.store.jobs()[1]
    assert (job["source_kind"], job["source_id"], job["url"]) == ("video", "dQw4w9WgXcQ",
                                                                  "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert load_settings()["downloads"]["playlist_links"] == "ask"
    saved = []
    queue.settingsSaved.connect(lambda: saved.append(True))
    queue.addLinks(IN_LIST, "audio")
    queue.answerPlaylist("playlist", True)
    assert saved == [True]  # Preferences reads the remembered answer again
    job = context.store.jobs()[2]
    assert (job["source_kind"], job["source_id"], job["url"]) == ("playlist", "PLabcdefghijklmnop", IN_LIST)
    assert json.loads(job["options_json"])["kind"] == "audio"
    assert load_settings()["downloads"]["playlist_links"] == "playlist"
    queue.addLinks(IN_LIST, "video")  # remembered: no question
    assert asked == [1, 1] and len(context.store.jobs()) == 4


def test_cancelling_the_question_drops_the_waiting_links(qapp, queue, context):
    queue.pauseAll()
    queue.addLinks(IN_LIST, "video")
    queue.answerPlaylist("", True)
    assert context.store.jobs() == [] and load_settings()["downloads"]["playlist_links"] == "ask"
    queue.answerPlaylist("video", False)  # nothing waits any more
    assert context.store.jobs() == []


def test_the_question_names_and_pictures_the_video_and_its_playlist(qapp, context):
    """The waiting link's video and playlist titles and thumbnails come from oEmbed, and go with the answer."""
    asked = []

    def fetch(url):
        asked.append(url)
        if "playlist%3Flist%3DPLabcdefghijklmnop" in url:
            return {"title": "Road trip", "author_name": "Someone", "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg"}
        return {"title": "Never Gonna Give You Up", "author_name": "Rick Astley",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}

    queue = QueueController(context, ToolManager(context), Notifier(lambda: None, lambda path: None),
                            quick_fetch=fetch)
    try:
        queue.pauseAll()
        queue.addLinks(IN_LIST, "video")
        assert wait_for(qapp, lambda: queue.heldVideo and queue.heldPlaylist, timeout=5.0)
        assert queue.heldVideo == {"title": "Never Gonna Give You Up", "uploader": "Rick Astley",
                                   "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}
        assert queue.heldPlaylist["title"] == "Road trip"
        assert any("watch%3Fv%3DdQw4w9WgXcQ%26" not in url and "dQw4w9WgXcQ" in url for url in asked)
        queue.addLinks("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLother", "video")
        assert len(asked) == 2  # a second link joins the open question; the first one's details stay
        queue.answerPlaylist("video", False)
        assert queue.heldVideo == {} and queue.heldPlaylist == {}
    finally:
        queue.shutdown()


def test_links_from_outside_open_download_options_when_smart_mode_is_off(qapp, queue, context):
    queue.pauseAll()
    requested = []
    queue.optionsRequested.connect(lambda links, kind: requested.append((links, kind)))
    settings = load_settings()
    settings["downloads"]["smart_mode"] = False
    save_settings(settings)
    assert queue.receiveLinks("https://fake.test/ok fake.test/flaky", "audio") == 2
    assert requested == [(["https://fake.test/ok", "https://fake.test/flaky"], "audio")] and context.store.jobs() == []
    settings["downloads"]["smart_mode"] = True
    save_settings(settings)
    assert queue.receiveLinks("https://fake.test/ok", "audio") == 1
    assert json.loads(context.store.jobs()[0]["options_json"])["kind"] == "audio"


def test_smart_mode_uses_the_video_or_audio_defaults(qapp, queue, context):
    """Audio has its own "Save in the file" choices; the video quality default applies."""
    queue.pauseAll()
    settings = load_settings()
    settings["formats"].update({"max_height": 720, "embed_thumbnail": True, "audio_embed_cover": False})
    save_settings(settings)
    queue.addLinks("https://fake.test/ok", "video")
    queue.addLinks("https://fake.test/ok", "audio")
    video, audio = (json.loads(job["options_json"]) for job in context.store.jobs())
    assert (video["kind"], video["max_height"], video["embed_thumbnail"]) == ("video", 720, True)
    assert (audio["kind"], audio["embed_thumbnail"]) == ("audio", False)


def _history(context: AppContext) -> list[tuple[str, str]]:
    """(kind, file name) of each library record, sorted."""
    return sorted((record["kind"], Path(record["filepath"]).name) for record in context.store.history())


def test_a_picture_site_link_saves_its_pictures(qapp, queue, context, tmp_path):
    """A picture site's link saves pictures whatever was chosen, in the pictures folder."""
    assert queue.addLinks("https://imgur.com/a/album1", "audio") == 1
    assert wait_for(qapp, lambda: states(context) == ["done"])
    job = context.store.jobs()[0]
    assert json.loads(job["options_json"])["kind"] == "photo" and job["output_root"] == str(tmp_path / "Pictures")
    assert job["message"] == "3 pictures saved"
    assert wait_for(qapp, lambda: len(context.store.history()) == 3)
    assert _history(context) == [("photo", "album 01.jpg"), ("photo", "album 02.png"), ("photo", "album 03.gif")]
    folder = tmp_path / "Pictures" / "Imgur album1"
    assert sorted(path.name for path in folder.iterdir()) == ["album 01.jpg", "album 02.png", "album 03.gif"]
    assert queue.model.get(0)["kind"] == "photo"
    # Saved before: the archive skips them all.
    queue.addLinks("https://imgur.com/a/album1", "video")
    assert wait_for(qapp, lambda: states(context) == ["done", "done"])
    assert context.store.jobs()[1]["message"] == "All 3 were downloaded before"


def test_a_direct_picture_link_keeps_its_name(qapp, queue, context, tmp_path):
    assert queue.addLinks("https://fake.test/sunset.jpg", "video") == 1
    assert wait_for(qapp, lambda: states(context) == ["done"])
    assert (tmp_path / "Pictures" / "sunset.jpg").read_bytes() == b"direct"
    assert wait_for(qapp, lambda: _history(context) == [("photo", "sunset.jpg")])


def test_a_post_saves_its_videos_then_its_pictures(qapp, queue, context, tmp_path, fake_gallerydl):
    assert queue.addLinks("https://x.com/mixed/status/1", "video") == 1
    assert wait_for(qapp, lambda: states(context) == ["done"])
    assert context.store.jobs()[0]["message"] == "1 video and 1 picture saved"
    assert wait_for(qapp, lambda: len(context.store.history()) == 2)
    assert _history(context) == [("photo", "mixed 01.jpg"), ("video", "Mixed Post (720p).mp4")]
    # The pictures pass leaves the post's videos to yt-dlp, and its one picture needs no folder.
    argv = json.loads((Path(fake_gallerydl[-1]) / "gallery-argv.json").read_text(encoding="utf-8"))
    assert "--filter" in argv and "extractor.twitter.videos=false" in argv
    assert (tmp_path / "Pictures" / "mixed 01.jpg").is_file() and not (tmp_path / "Pictures" / "X (Twitter) 1").exists()
    picture = next(record for record in context.store.history() if record["kind"] == "photo")
    assert picture["output_root"] == str(tmp_path / "Pictures")


def test_a_post_with_pictures_only_is_done_with_them(qapp, queue, context, tmp_path):
    """yt-dlp finds no video in it; the pictures pass saves the post's pictures in its own folder."""
    assert queue.addLinks("https://x.com/pictures/status/2", "video") == 1
    assert wait_for(qapp, lambda: states(context) == ["done"])
    job = context.store.jobs()[0]
    assert job["message"] == "4 pictures saved" and job["error_key"] == ""
    folder = tmp_path / "Pictures" / "X (Twitter) 2"
    assert sorted(path.name for path in folder.iterdir()) == ["post 01.jpg", "post 02.jpg", "post 03.webp",
                                                              "post 04.jpg"]


def test_saving_pictures_can_be_turned_off(qapp, queue, context):
    settings = load_settings()
    settings["downloads"]["save_photos"] = False
    save_settings(settings)
    queue.addLinks("https://x.com/pictures/status/2", "video")
    assert wait_for(qapp, lambda: states(context) == ["failed"])
    assert context.store.jobs()[0]["message"] == "This post has only pictures, no video."


def test_a_spotify_album_downloads_its_songs_from_youtube(qapp, queue, context, tmp_path):
    """Queued as songs whatever was chosen; each found song is saved, named, and listed under the album."""
    from tests.core.test_spotify import ALBUM_ID, album_page
    from gfgmd.controllers import queue_ctrl

    class Offline(queue_ctrl.SpotifyExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, page=lambda url: album_page("Song One", "Nowhere", "Song Three"),
                             cover=lambda url: b"\xff\xd8\xff", **kwargs)
    with patch.object(queue_ctrl, "SpotifyExecutor", Offline):
        assert queue.addLinks(f"https://open.spotify.com/album/{ALBUM_ID}?si=share", "video") == 1
        assert wait_for(qapp, lambda: states(context) in (["done"], ["failed"]))
    job = context.store.jobs()[0]
    assert json.loads(job["options_json"])["kind"] == "audio" and job["output_root"] == str(tmp_path / "Music")
    assert job["state"] == "done" and job["message"] == "2 songs saved, 1 couldn't be downloaded"
    assert job["title"] == "Fake Album"
    assert wait_for(qapp, lambda: len(context.store.history()) == 2)
    assert sorted(Path(record["filepath"]).name for record in context.store.history()) == [
        "Fake Artist - Song One.mp4", "Fake Artist - Song Three.mp4"]
    items = {item["title"]: item["state"] for item in context.store.job_items(job["id"])}
    assert items == {"Fake Artist - Song One": "done", "Fake Artist - Nowhere": "skipped",
                     "Fake Artist - Song Three": "done"}



def test_download_again_saves_a_picture_again(qapp, queue, context, tmp_path):
    """Download again on a library picture saves it once more, past the pictures archive."""
    queue.addLinks("https://imgur.com/a/album1", "video")
    assert wait_for(qapp, lambda: states(context) == ["done"])
    queue.download_again("https://imgur.com/a/album1", "photo", "jpg")
    assert wait_for(qapp, lambda: states(context) == ["done", "done"])
    again = context.store.jobs()[1]
    options = json.loads(again["options_json"])
    assert (options["kind"], options["ignore_archive"]) == ("photo", True)
    assert again["message"] == "3 pictures saved"
