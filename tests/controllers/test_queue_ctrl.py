"""The queue controller end to end with the fake yt-dlp: adding, running, finishing, and stopping."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers.queue_ctrl import QueueController
from gfgmd.core import naming
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet
from gfgmd.services.context import AppContext
from gfgmd.services.notifier import Notifier
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.settings import get_default_settings, save_settings

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> AppContext:
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    settings = get_default_settings()
    settings["downloads"]["folder"] = str(tmp_path / "Downloads")
    settings["notifications"]["enabled"] = False
    save_settings(settings)
    yield context
    context.close()


@pytest.fixture(autouse=True)
def fixed_quality():
    with patch.object(naming, "video_quality", return_value=720):
        yield


@pytest.fixture
def queue(qapp, context, fake_ytdlp):
    def runner(command, on_line, stop):
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
    assert queue.addLinks("https://fake.test/ok", "video-1080") == 1
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
    assert queue.addLinks("not a link\nftp://x/y", "video-1080") == 0
    assert context.store.jobs() == []
    assert notices and "skipped" in notices[0]


def test_sign_in_needed_then_retry_after_sign_in(qapp, queue, context):
    sites = []
    queue.signInNeeded.connect(sites.append)
    queue.addLinks("https://fake.test/auth", "video-1080")
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"])
    job = context.store.jobs()[0]
    assert job["action"] == "signin" and sites == [job["site"]]
    queue.retrySignIn(job["site"])
    assert wait_for(qapp, lambda: states(context) == ["needs_auth"] and context.store.jobs()[0]["attempts"] == 1)


def test_full_disk_pauses_the_queue(qapp, queue, context):
    queue.addLinks("https://fake.test/disk", "video-1080")
    assert wait_for(qapp, lambda: states(context) == ["paused"])
    assert queue.paused is True
    queue.addLinks("https://fake.test/ok", "video-1080")
    qapp.processEvents()
    assert states(context) == ["paused", "queued"]  # nothing starts while paused
    queue.resumeAll()
    assert wait_for(qapp, lambda: "done" in states(context))


def test_pause_resume_and_cancel_a_running_download(qapp, queue, context):
    queue.addLinks("https://fake.test/slow", "video-1080")
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
    queue.addLinks("https://fake.test/slow\nhttps://fake.test/ok", "video-1080")
    assert wait_for(qapp, lambda: queue.runningCount == 1)
    assert sorted(states(context)) == ["queued", "running"]
    queue.pauseAll()
    assert wait_for(qapp, lambda: queue.runningCount == 0)


def test_when_done_countdown(qapp, queue, context):
    countdowns = []
    queue.whenDoneCountdown.connect(countdowns.append)
    queue.setWhenDone("sleep")
    queue.addLinks("https://fake.test/ok", "video-1080")
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
    queue.remove(second)
    assert [job["id"] for job in context.store.jobs()] == [first]
    assert queue.model.count == 1
