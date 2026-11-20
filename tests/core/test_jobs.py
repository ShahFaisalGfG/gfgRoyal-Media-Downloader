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


def test_lines_posing_as_the_apps_are_ignored(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """A title holding "@@gfgr:file" lines (the plain marker, or a file outside the folder) is never
    taken for a saved file: the victim file is left alone and only the real video counts."""
    seen: list[Path] = []
    spec = make_spec(tmp_path, "forged")
    executor = JobExecutor(spec, lambda: TOOLS, on_file=lambda info, path: seen.append(path),
                           runner=fake_runner(fake_ytdlp))
    result = executor.run()
    assert result.state == "done" and [path.name for path in seen] == ["Clip (720p).mp4"]
    victim = Path(fake_ytdlp[fake_ytdlp.index("--fake-state") + 1]) / "victim.mp3"
    assert victim.read_bytes() == b"theirs"


def test_each_run_has_its_own_marker(tmp_path: Path) -> None:
    """The marker in yt-dlp's print templates differs between runs, so no site can know it."""
    first = JobExecutor(make_spec(tmp_path, "ok"), lambda: TOOLS)
    second = JobExecutor(make_spec(tmp_path, "ok"), lambda: TOOLS)
    assert first._marker != second._marker and first._marker.startswith("@@gfgr-")


def test_a_file_that_breaks_finishing_does_not_hang_the_download(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Something unexpected while finishing a file (a probe that timed out) is noted; the run still ends."""
    import subprocess

    def stuck(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 60)

    spec = make_spec(tmp_path, "ok")
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    done = threading.Event()
    outcome: list = []
    with patch("gfgmd.core.jobs.finalize_file", side_effect=stuck):
        worker = threading.Thread(target=lambda: (outcome.append(executor.run()), done.set()), daemon=True)
        worker.start()
        assert done.wait(30), "the download hung after a file failed to finish"
    result = outcome[0]
    assert result.state == "done" and len(result.files) == 1
    with patch("gfgmd.core.jobs.JobExecutor._finish", side_effect=KeyError("boom")):
        again = JobExecutor(make_spec(tmp_path / "again", "ok"), lambda: TOOLS, runner=fake_runner(fake_ytdlp))
        finished = threading.Event()
        thread = threading.Thread(target=lambda: (again.run(), finished.set()), daemon=True)
        thread.start()
        assert finished.wait(30), "the finishing thread died and the download hung"


def test_a_download_again_keeps_what_it_saved_across_runs(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Paused and resumed (a new run), a Download again doesn't fetch its saved videos a second time."""
    spec = make_spec(tmp_path, "ok")
    spec = JobSpec(spec.url, spec.source, spec.options.with_changes(ignore_archive=True), spec.paths, retry_delay=1)
    first = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run()
    second = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run()
    assert len(first.files) == 1 and second.files == [] and second.archived == 1


def test_a_playlist_video_that_keeps_failing_is_skipped(tmp_path: Path) -> None:
    """After ITEM_ATTEMPTS attempts failing the same way of its own, the video is left out; the
    connection, rate limits, and attempts that got nowhere never count against it."""
    from gfgmd.core.errors import CATEGORIES, Failure, Policy
    from gfgmd.core.jobs import ITEM_ATTEMPTS, _give_up_on_repeats
    counts: dict[str, int] = {}
    failure = Failure(CATEGORIES["postprocess"], "Conversion failed!", "bbbbbbbbbbb")
    for _ in range(ITEM_ATTEMPTS - 1):
        assert _give_up_on_repeats([failure], counts, True)[0].category.policy is Policy.RETRY
    assert _give_up_on_repeats([failure], counts, False)[0].category.policy is Policy.RETRY  # got nowhere
    assert _give_up_on_repeats([failure], counts, True)[0].category.policy is Policy.SKIP
    assert _give_up_on_repeats([], counts, True) == [] and counts == {}  # a clean attempt forgets it
    for key in ("rate_limited", "bot_check"):
        limited = Failure(CATEGORIES[key], "HTTP Error 429", "bbbbbbbbbbb")
        for _ in range(ITEM_ATTEMPTS + 1):
            assert _give_up_on_repeats([limited], counts, True)[0].category.policy is not Policy.SKIP
    # A dropped connection counts only in attempts that got somewhere: an outage never gives a video up,
    # a video whose server never answers while the rest download does.
    dropped = Failure(CATEGORIES["network"], "Connection reset", "ccccccccccc")
    for _ in range(ITEM_ATTEMPTS + 1):
        assert _give_up_on_repeats([dropped], counts, False)[0].category.policy is Policy.RETRY
    for _ in range(ITEM_ATTEMPTS - 1):
        assert _give_up_on_repeats([dropped], counts, True)[0].category.policy is Policy.RETRY
    assert _give_up_on_repeats([dropped], counts, True)[0].category.policy is Policy.SKIP


def test_a_video_that_breaks_off_without_naming_itself_is_skipped(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Its error ("fragment 30 not found") names no video, yet it is the one given up on: the list
    finishes instead of trying again forever, and each wait says why."""
    spec = make_spec(tmp_path, "idless", kind="playlist")
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    reasons: list[str] = []
    result = executor.run(sleep=lambda seconds: reasons.append(executor.snapshot().reason) or False)
    assert result.state == "done" and len(result.files) == 1
    assert [failure.item_id for failure in result.skipped] == ["bbbbbbbbbbb"]
    assert reasons and all(reason for reason in reasons)
    # Not signed in: nothing to try without a sign-in.
    assert not (Path(fake_ytdlp[-1]) / "attempts-alone.txt").exists()


def test_a_signed_in_lists_video_that_breaks_off_is_saved_without_the_sign_in(fake_ytdlp: list[str],
                                                                              tmp_path: Path) -> None:
    """It breaks off only with the sign-in (as YouTube's signed-in players can), so it is downloaded by
    its own link without the sign-in, into the list's folder, and the list finishes at once."""
    spec = make_spec(tmp_path, "idless", kind="playlist", auth=Auth(cookies_file=str(tmp_path / "cookies.txt")))
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    waits: list[float] = []
    result = executor.run(sleep=lambda seconds: waits.append(seconds) or False)
    assert result.state == "done" and not result.skipped and not waits
    assert sorted(path.parent.name for path in result.files) == ["Fake List", "Fake List"]
    assert result.message == "2 videos saved"
    argv = json.loads((Path(fake_ytdlp[-1]) / "argv.json").read_text())
    assert argv[argv.index("--") + 1:] == ["https://fake.test/alone/bbbbbbbbbbb"] and "--cookies" not in argv
    rows = [value[1] for kind, value in executor.take_updates() if kind == "state" and value[0] == "bbbbbbbbbbb"]
    assert rows == ["failed", "pending"]


def test_a_video_that_fails_without_the_sign_in_too_is_tried_so_once(fake_ytdlp: list[str], tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """Its own link fails as well: it keeps its first failure (its row too) and is given up on as before."""
    monkeypatch.setenv("FAKE_ALONE_FAILS", "1")
    spec = make_spec(tmp_path, "idless", kind="playlist", auth=Auth(cookies_file=str(tmp_path / "cookies.txt")))
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp))
    result = executor.run(sleep=lambda seconds: False)
    assert result.state == "done" and len(result.files) == 1
    assert [failure.item_id for failure in result.skipped] == ["bbbbbbbbbbb"]
    assert (Path(fake_ytdlp[-1]) / "attempts-alone.txt").read_text() == "1"
    rows = [value for kind, value in executor.take_updates() if kind == "state" and value[0] == "bbbbbbbbbbb"]
    # Failed, tried alone, failed alone (another reason), then its first failure again.
    assert [row[1] for row in rows[:2]] == ["failed", "pending"] and rows[3] == rows[0]


def test_a_video_whose_server_never_answers_is_skipped(fake_ytdlp: list[str], tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Stalling attempt after attempt, it is left out after ITEM_ATTEMPTS stalls; the rest is saved."""
    monkeypatch.setenv("FAKE_STALLS", "9")
    spec = make_spec(tmp_path, "stall", kind="playlist")
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp), stall_seconds=1.0)
    result = executor.run(sleep=lambda seconds: False)
    assert result.state == "done" and len(result.files) == 2
    assert [failure.item_id for failure in result.skipped] == ["bbbbbbbbbbb"]
    assert result.skipped[0].category.final == "The download server didn't answer. Try again later."


def test_an_error_about_the_list_names_no_video(tmp_path: Path) -> None:
    """The playlist's own ID (in its link, or a list file read) is never taken for a video's."""
    executor = JobExecutor(make_spec(tmp_path, "playlist", kind="playlist"), lambda: TOOLS)
    assert executor._video_id("playlist") == "" and executor._video_id("bbbbbbbbbbb") == "bbbbbbbbbbb"
    # A watch link picked from a playlist names a video too; that one is still a video.
    spec = make_spec(tmp_path, "playlist", kind="playlist")
    watch = JobSpec("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLfake", spec.source, spec.options, spec.paths)
    executor = JobExecutor(watch, lambda: TOOLS)
    assert executor._video_id("aaaaaaaaaaa") == "aaaaaaaaaaa" and executor._video_id("PLfake") == ""


def test_a_download_folder_that_cant_be_made_says_so(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """The folder sits where a file is (a drive gone, a bad path): a plain failure with Choose folder."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    spec = make_spec(blocker, "ok")
    result = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run()
    assert result.state == "failed" and result.failure is not None
    assert result.failure.category.action == "choose_folder"


def test_a_summary_leaves_out_nothing_saved() -> None:
    from gfgmd.core.errors import CATEGORIES, Failure
    from gfgmd.core.jobs import JobResult
    skipped = [Failure(CATEGORIES["network"], "", "bbbbbbbbbbb")]
    assert JobResult("done", archived=7, skipped=skipped).message == "7 downloaded before, 1 couldn't be downloaded"
    assert JobResult("done", skipped=skipped, kind="audio").message == "1 song couldn't be downloaded"
    assert JobResult("done", files=[Path("a.mp4")], archived=2).message == "1 video saved, 2 downloaded before"


def test_a_lists_video_downloaded_before_is_marked_as_it_is_passed_over(tmp_path: Path) -> None:
    """yt-dlp names a list's video it passes over by its ID, then its title (which may hold ": ")."""
    executor = JobExecutor(make_spec(tmp_path, "playlist", kind="playlist"), lambda: TOOLS)
    executor._feed("out", "[download] v2aaaaaaaaa: Mix: Best of has already been recorded in the archive")
    assert executor.take_updates() == [("state", ("v2aaaaaaaaa", "archived", ""))]


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
    assert result.state == "failed" and result.attempts == 1 and result.message == "This is private."


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


# ── Playlists: their lists, files finished as they land, stalls, and batches ──

def test_playlist_lists_its_videos_and_finishes_each_file_as_it_lands(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """yt-dlp's playlist file gives every video up front; each file is renamed while the rest download."""
    finished: list[tuple[str, bool]] = []
    running = threading.Event()

    def runner(command, on_line, stop):
        running.set()
        try:
            return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
        finally:
            running.clear()

    spec = make_spec(tmp_path, "listed", kind="playlist")
    executor = JobExecutor(spec, lambda: TOOLS, runner=runner,
                           on_file=lambda info, path: finished.append((path.name, running.is_set())))
    result = executor.run(sleep=lambda seconds: False)
    assert result.state == "done" and len(result.files) == 3
    assert [name for name, _ in finished] == ["First (720p).mp4", "Second (720p).mp4", "Third (720p).mp4"]
    assert finished[0][1] is True  # renamed and reported before yt-dlp finished the list
    listed = [entries for kind, entries in executor.take_updates() if kind == "listed"]
    assert len(listed) == 1 and [(e["id"], e["index"]) for e in listed[0]] == [
        ("aaaaaaaaaaa", 1), ("bbbbbbbbbbb", 2), ("ccccccccccc", 3)]
    assert listed[0][0]["thumbnail"].endswith("/aaaaaaaaaaa/hq.jpg") and listed[0][0]["title"] == "First"
    argv = json.loads((Path(fake_ytdlp[-1]) / "argv.json").read_text())
    assert "--no-clean-info-json" in argv and "infojson:" in argv


def test_a_stalled_video_waits_while_the_rest_of_the_list_finishes(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """The second video's server stops answering: the third downloads first, then the second, fresh."""
    order: list[str] = []
    spec = make_spec(tmp_path, "stall", kind="playlist")
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp), stall_seconds=1.0,
                           on_file=lambda info, path: order.append(str(info["id"])))
    waits: list[float] = []
    result = executor.run(sleep=lambda seconds: waits.append(seconds) or False)
    assert result.state == "done" and len(result.files) == 3
    assert result.message == "3 videos saved"  # not the run's own videos counted again as "downloaded before"
    assert order == ["aaaaaaaaaaa", "ccccccccccc", "bbbbbbbbbbb"] and waits == []
    assert result.attempts == 1 and executor.retries == 0  # setting a video aside is no failed try
    states = [value for kind, value in executor.take_updates() if kind == "state"]
    assert ("bbbbbbbbbbb", "deferred", "The download server didn't answer; trying again soon.") in states
    assert states.index(("bbbbbbbbbbb", "pending", "")) > states.index(
        ("bbbbbbbbbbb", "deferred", "The download server didn't answer; trying again soon."))


def test_a_video_that_stalls_again_waits_before_its_next_try(fake_ytdlp: list[str], tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_STALLS", "2")
    spec = make_spec(tmp_path, "stall", kind="playlist")
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp), stall_seconds=1.0)
    waits: list[float] = []
    result = executor.run(sleep=lambda seconds: waits.append(seconds) or False)
    assert result.state == "done" and len(result.files) == 3 and len(waits) == 1
    assert result.attempts == 2 and executor.retries == 1


def test_a_single_video_that_stalls_waits_and_tries_again(fake_ytdlp: list[str], tmp_path: Path) -> None:
    stops = []
    spec = make_spec(tmp_path, "slow", max_attempts=2)
    executor = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp), stall_seconds=1.0)
    result = executor.run(sleep=lambda seconds: stops.append(seconds) or False)
    assert result.state == "failed" and result.attempts == 2 and len(stops) == 1
    assert result.message == "The download server didn't answer. Try again later."


def test_a_batch_of_links_downloads_into_a_named_folder(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """A playlist subscription's new uploads: one link each, filed under the subscription's name."""
    spec = make_spec(tmp_path, "batch", kind="playlist", urls=("https://fake.test/batch/aaaaaaaaaaa",
                                                                "https://fake.test/batch/bbbbbbbbbbb"),
                     folder="Mix: Best of")
    result = JobExecutor(spec, lambda: TOOLS, runner=fake_runner(fake_ytdlp)).run(sleep=lambda seconds: False)
    assert result.state == "done" and len(result.files) == 2
    assert {path.parent.name for path in result.files} == {"Mix_ Best of"}
    argv = json.loads((Path(fake_ytdlp[-1]) / "argv.json").read_text())
    assert argv[argv.index("--") + 1:] == list(spec.urls)


def test_an_empty_list_says_so() -> None:
    from gfgmd.core.jobs import JobResult
    assert JobResult("done").message == "There was nothing to download: the list is empty"
    assert JobResult("done", archived=2).message == "All 2 were downloaded before"
