"""The job executor end to end with the fake yt-dlp: success, retries, skips, sign-in, and stops."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.core import naming
from gfgmd.core.archive import archive_path
from gfgmd.core.command import Auth, RunPaths
from gfgmd.core.jobs import JobExecutor, JobSpec
from gfgmd.core.options import DownloadOptions
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import Source
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


def make_spec(tmp_path: Path, scenario: str, kind: str = "video", **changes) -> JobSpec:
    source = Source(kind, "PLfake" if kind == "playlist" else "aaaaaaaaaaa")
    options = DownloadOptions()
    root = tmp_path / "Downloads"
    paths = RunPaths(root, archive_path(root, source, options.profile), root / ".gfgmd" / "jobs" / "x",
                     tmp_path / "cache")
    return JobSpec(f"https://fake.test/{scenario}", source, options, paths, retry_delay=1, **changes)


def fake_runner(prefix: list[str]):
    def run(command, on_line, stop):
        return run_to_completion(prefix + command[1:], on_line, stop)
    return run


@pytest.fixture(autouse=True)
def fixed_quality():
    with patch.object(naming, "video_quality", return_value=720):
        yield


def test_success_renames_and_reports(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Download, rename to "Title (quality)", and report the file once."""
    seen: list[Path] = []
    spec = make_spec(tmp_path, "ok")
    executor = JobExecutor(spec, lambda: TOOLS, on_file=lambda info, path: seen.append(path),
                           runner=fake_runner(fake_ytdlp))
    result = executor.run(sleep=lambda seconds: False)
    assert result.state == "done" and result.attempts == 1
    final = spec.paths.root / "Clip (720p).mp4"
    assert result.files == [final] and seen == [final] and final.exists()
    argv = json.loads((Path(fake_ytdlp[-1]) / "argv.json").read_text())
    assert argv[argv.index("--download-archive") + 1] == str(spec.paths.archive)


def test_network_failure_retries_with_backoff(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Retry a temporary failure after the backoff delay, then succeed."""
    waits: list[float] = []
    executor = JobExecutor(make_spec(tmp_path, "flaky"), lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    result = executor.run(sleep=lambda seconds: waits.append(seconds) or False)
    assert result.state == "done" and result.attempts == 2
    assert waits == [1]


def test_attempt_limit(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Give up after max_attempts temporary failures."""
    spec = make_spec(tmp_path, "flaky", max_attempts=1)
    result = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run(sleep=lambda s: False)
    assert result.state == "failed" and result.attempts == 1
    assert result.failure is not None and result.failure.category.key == "network"


def test_private_item_is_skipped_not_retried_forever(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Finish a playlist whose one private video can never download, without endless retries."""
    executor = JobExecutor(make_spec(tmp_path, "playlist", kind="playlist"), lambda: TOOLS,
                           runner=fake_runner(fake_ytdlp))
    result = executor.run(sleep=lambda seconds: False)
    assert result.state == "done" and result.attempts == 1
    assert [failure.item_id for failure in result.skipped] == ["bbbbbbbbbbb"]
    assert sorted(path.name for path in result.files) == ["First (720p).mp4", "Third (720p).mp4"]


def test_single_private_video_fails_once(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Signed in, a single private video fails at once with its reason: the account can't see it."""
    spec = make_spec(tmp_path, "private", auth=Auth(cookies_file=str(tmp_path / "cookies.txt")))
    result = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run(sleep=lambda s: False)
    assert result.state == "failed" and result.attempts == 1 and result.message == "Private video"


def test_single_private_video_asks_for_a_sign_in(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Signed out, a private video may be the user's own, so the job waits for a sign-in."""
    result = JobExecutor(make_spec(tmp_path, "private"), lambda: TOOLS,
                         runner=fake_runner(fake_ytdlp)).run(sleep=lambda s: False)
    assert result.state == "needs_auth" and result.attempts == 1
    assert result.failure is not None and result.failure.category.key == "private_signin"


def test_sign_in_needed_stops(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Stop and ask for a sign-in instead of retrying an age-restricted video."""
    result = JobExecutor(make_spec(tmp_path, "auth"), lambda: TOOLS,
                         runner=fake_runner(fake_ytdlp)).run(sleep=lambda s: False)
    assert result.state == "needs_auth" and result.failure is not None
    assert result.failure.category.action == "signin"


def test_disk_full_pauses_the_queue(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Report a full disk so the queue pauses."""
    result = JobExecutor(make_spec(tmp_path, "disk"), lambda: TOOLS,
                         runner=fake_runner(fake_ytdlp)).run(sleep=lambda s: False)
    assert result.state == "disk_full"


def test_stop_during_download(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Stop a running download from another thread."""
    executor = JobExecutor(make_spec(tmp_path, "slow"), lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    results = []
    worker = threading.Thread(target=lambda: results.append(executor.run()))
    worker.start()
    deadline = time.monotonic() + 30
    while executor.snapshot().stage not in ("Downloading",) and time.monotonic() < deadline:
        time.sleep(0.05)
    executor.stop()
    worker.join(30)
    assert results and results[0].state == "stopped"


def test_stop_during_retry_wait(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Stop cuts the wait between attempts short."""
    executor = JobExecutor(make_spec(tmp_path, "flaky"), lambda: TOOLS, runner=fake_runner(fake_ytdlp))

    def wait(seconds: float) -> bool:
        executor.stop()
        return True
    assert executor.run(sleep=wait).state == "stopped"


def test_missing_tools_fail(tmp_path: Path) -> None:
    """Report missing tools without starting anything."""
    def tools() -> ToolSet:
        raise RuntimeError("Missing required programs: yt-dlp")
    result = JobExecutor(make_spec(tmp_path, "ok"), tools).run(sleep=lambda s: False)
    assert result.state == "failed" and result.failure is not None and result.failure.category.key == "tools"
