"""The queue controller end to end with the fake yt-dlp: adding, running, finishing, and stopping."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers.queue_ctrl import QueueController
from gfgmd.core import extract, naming
from gfgmd.core.extract import VideoProbe
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
    assert row["jobState"] == "done" and row["title"] == "Clip"
    assert queue.busy is False


def test_bad_links_are_reported_not_queued(qapp, queue, context):
    notices = []
    queue.notice.connect(notices.append)
    assert queue.addLinks("not a link\nftp://x/y", "video-best-mp4") == 0
    assert context.store.jobs() == []
    assert notices and "skipped" in notices[0]


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


def test_interrupted_jobs_resume_on_start(qapp, context, fake_ytdlp):
    job_id = context.store.add_job("https://fake.test/ok", "generic", "https://fake.test/ok", "fake.test",
                                   {"kind": "video"}, str(Path(context.store.path).parent / "D"), state="running")
    notifier = Notifier(lambda: None, lambda path: None)
    controller = QueueController(context, ToolManager(context), notifier,
                                 runner=lambda c, o, s: run_to_completion(fake_ytdlp + c[1:], o, s))
    try:
        assert wait_for(qapp, lambda: context.store.job(job_id)["state"] == "done")
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
