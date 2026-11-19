"""Analyze, library, subscriptions, sign-ins, preferences, and tools controllers."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers import analyze_ctrl, subscriptions_ctrl
from gfgmd.controllers.analyze_ctrl import AnalyzeController
from gfgmd.controllers.library_ctrl import LibraryController
from gfgmd.controllers.prefs_ctrl import PrefsController
from gfgmd.controllers.queue_ctrl import QueueController
from gfgmd.controllers.signins_ctrl import SignInsController
from gfgmd.controllers.subscriptions_ctrl import SubscriptionsController
from gfgmd.core import analyze as analyze_module
from gfgmd.core.archive import archive_path, read_archive_ids
from gfgmd.core.auth import Cookie, format_netscape
from gfgmd.core.options import DownloadOptions
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import source_from_url
from gfgmd.core.tools import ToolSet
from gfgmd.services.context import AppContext
from gfgmd.services import recycle as recycle_module
from gfgmd.services.notifier import Notifier
from gfgmd.services.tool_manager import ToolManager
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")
FUTURE = int(time.time()) + 86400 * 30


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


@pytest.fixture
def paused_queue(qapp, context):
    notifier = Notifier(lambda: None, lambda path: None)
    queue = QueueController(context, ToolManager(context), notifier)
    queue.pauseAll()  # nothing runs: these tests look at what gets queued
    yield queue
    queue.shutdown()


def fake_runner(prefix):
    def run(command, on_line, stop=None, env=None, cwd=None, max_line_bytes=1024 * 1024):
        return run_to_completion(prefix + command[1:], on_line, stop, max_line_bytes=max_line_bytes)
    return run


def wait_for(qapp, condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


# ── Analyze ───────────────────────────────────────────────────────────────

def test_analyze_then_queue_a_subset(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    controller = AnalyzeController(context, paused_queue)
    with patch.object(analyze_module, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        controller.analyze("https://www.youtube.com/playlist?list=PLfake")
        assert wait_for(qapp, lambda: controller.hasResult)
    assert controller.title == "Fake List" and controller.isPlaylist and controller.entries.totalCount == 2
    controller.entries.toggle(1)  # keep only the first video
    assert controller.addToQueue({"kind": "audio", "audio_format": "mp3"})
    job = context.store.jobs()[0]
    options = json.loads(job["options_json"])
    assert (options["kind"], options["items"]) == ("audio", "1")
    assert [item["item_id"] for item in context.store.job_items(job["id"])] == ["aaaaaaaaaaa"]
    assert controller.hasResult is False
    controller.shutdown()


def test_private_playlist_offers_sign_in_then_reads_again(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    """Signed out, a private playlist offers Sign in; signing in to that site reads the link again."""
    controller = AnalyzeController(context, paused_queue)
    real = fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])
    calls = []

    def runner(command, on_line, stop=None, env=None, cwd=None, max_line_bytes=1024 * 1024):
        calls.append(command)
        if len(calls) == 1:
            on_line("err", "ERROR: [youtube:tab] PLfake: YouTube said: The playlist does not exist.")
            return 1, False
        return real(command, on_line, stop, env, cwd, max_line_bytes)

    with patch.object(analyze_module, "run_to_completion", runner):
        controller.analyze("https://www.youtube.com/playlist?list=PLfake")
        assert wait_for(qapp, lambda: controller.errorAction == "signin")
        assert "Sign in" in controller.error
        controller.signedIn("instagram")  # another site's sign-in changes nothing
        assert len(calls) == 1
        controller.signedIn("youtube")
        assert wait_for(qapp, lambda: controller.hasResult)
    assert len(calls) == 2 and controller.error == ""
    controller.shutdown()


def test_analyze_reports_errors(qapp, context, paused_queue):
    controller = AnalyzeController(context, paused_queue)
    controller.analyze("ftp://nope")
    assert "https://" in controller.error
    controller.shutdown()


# ── Library ───────────────────────────────────────────────────────────────

def test_library_filters_and_recycle_bin(qapp, context, tmp_path):
    keep = tmp_path / "keep.mp4"
    keep.write_bytes(b"v")
    # The file's captions go with it; another file's lyrics ("keep.Remix" is its own song) stay.
    (tmp_path / "keep.en.srt").write_text("1", encoding="utf-8")
    (tmp_path / "keep.Remix.mp3").write_bytes(b"a")
    (tmp_path / "keep.Remix.lrc").write_text("[00:01.00]la", encoding="utf-8")
    context.store.add_history(str(keep), title="Lecture one", site="youtube", kind="video")
    context.store.add_history(str(tmp_path / "gone.mp3"), title="Song", site="soundcloud", kind="audio")
    library = LibraryController(context)
    assert library.total == 2
    library.setFilters("lecture", "", "")
    assert library.total == 1 and library.model.get(0)["missing"] is False
    library.setFilters("", "audio", "")
    assert library.model.get(0)["missing"] is True
    with patch.object(recycle_module, "to_recycle_bin", return_value=True) as recycle:
        library.setFilters("", "", "")
        lecture = next(library.model.get(i) for i in range(library.model.count) if library.model.get(i)["title"] == "Lecture one")
        library.deleteFiles([lecture["historyId"]])
    recycle.assert_called_once_with([str(keep), str(tmp_path / "keep.en.srt")])
    assert library.total == 1


# ── Subscriptions ─────────────────────────────────────────────────────────

def test_subscription_starts_from_new_uploads_then_queues_them(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    subs = SubscriptionsController(context, paused_queue, Notifier(lambda: None, lambda p: None))
    url = "https://www.youtube.com/@fake/videos"
    with patch.object(subscriptions_ctrl, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        assert subs.add(url, {}, 6, False, True)
        assert wait_for(qapp, lambda: subs.model.count == 1 and "Watching" in subs.model.get(0)["resultText"])
        source = source_from_url(url)
        archive = archive_path(Path(load_settings()["downloads"]["folder"]), source,
                               DownloadOptions.from_dict(json.loads(context.store.subscriptions()[0]["options_json"])).profile)
        assert read_archive_ids(archive) == {"nnnnnnnnnn3", "nnnnnnnnnn1", "ooooooooooo"}
        assert context.store.jobs() == []  # existing uploads were only recorded
        # A later check finds nothing new until a new upload appears.
        archive.write_text("youtube nnnnnnnnnn1\nyoutube ooooooooooo\n", encoding="utf-8")
        sub_id = context.store.subscriptions()[0]["id"]
        subs.checkNow(sub_id)
        assert wait_for(qapp, lambda: context.store.jobs() != [])
    urls = sorted(job["url"] for job in context.store.jobs())
    assert urls == ["https://www.youtube.com/watch?v=nnnnnnnnnn3"]
    assert context.store.seen(sub_id) == {"nnnnnnnnnn2": "skipped", "nnnnnnnnnn3": "queued"}
    subs.shutdown()


def test_subscription_rejects_single_videos(qapp, context, paused_queue):
    subs = SubscriptionsController(context, paused_queue, Notifier(lambda: None, lambda p: None))
    notices = []
    subs.notice.connect(notices.append)
    assert subs.add("https://youtu.be/jNQXAC9IVRw", {}, 6, False, True) is False
    assert "channel or a playlist" in notices[0]
    exported = json.loads(subs.exportJson())
    assert exported["subscriptions"] == []
    assert subs.importJson("not json") == 0
    subs.shutdown()


# ── Sign-ins ──────────────────────────────────────────────────────────────

def youtube_cookies() -> list[Cookie]:
    return [Cookie(".youtube.com", "/", "SAPISID", "s", expires=FUTURE), Cookie(".example.com", "/", "x", "y")]


def fake_check(code: int, error: str = ""):
    """A stand-in for the sign-in check's yt-dlp run: exits with `code` after printing `error`."""
    calls = []

    def run(command, on_line, stop):
        calls.append(command)
        if error:
            on_line("err", f"ERROR: {error}")
        return code, False
    run.calls = calls
    return run


def test_sign_in_from_file_and_sign_out(qapp, context, tmp_path):
    check = fake_check(0)
    signins = SignInsController(context, runner=check)
    signed = []
    signins.signedIn.connect(signed.append)
    offered = []
    signins.offerDeleteOriginal.connect(offered.append)
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(format_netscape(youtube_cookies()), encoding="utf-8")
    signins.importFile("youtube", str(cookie_file))
    account = context.store.account_for_site("youtube")
    assert account is not None and account["method"] == "file"
    # A YouTube sign-in is checked first by opening Watch later with the new cookies.
    assert wait_for(qapp, lambda: signed == ["youtube"])
    assert check.calls and check.calls[0][-1] == "https://www.youtube.com/playlist?list=WL"
    assert "--cookies" in check.calls[0]
    assert [c.name for c in context.vault.load(account["id"])] == ["SAPISID"]
    assert offered == [str(cookie_file)]
    row = next(signins.model.get(i) for i in range(signins.model.count) if signins.model.get(i)["siteKey"] == "youtube")
    assert row["status"] == "ok"
    signins.signOut("youtube")
    assert context.store.account_for_site("youtube") is None and not context.vault.exists(account["id"])
    signins.shutdown()


def test_companion_cookies_and_other_sites(qapp, context):
    signins = SignInsController(context)
    notices = []
    signins.notice.connect(notices.append)
    signins.receive_cookies("instagram", [Cookie(".instagram.com", "/", "csrftoken", "x")])
    assert context.store.account_for_site("instagram") is None and "no Instagram sign-in" in notices[-1]
    signins.receive_cookies("instagram", [Cookie(".instagram.com", "/", "sessionid", "x", expires=FUTURE)])
    assert context.store.account_for_site("instagram")["method"] == "extension"
    assert signins.addSite("https://media.example.org/watch/1") == "media.example.org"
    signins.useFirefox("media.example.org", "Work")
    assert context.store.account_for_site("media.example.org")["browser"] == "firefox:Work"
    signins.shutdown()


# ── Preferences ───────────────────────────────────────────────────────────

def test_preferences_save_and_presets(qapp, context):
    prefs = PrefsController(context)
    prefs.saveSettings({"downloads.concurrent": 2, "network.proxy": "socks5://127.0.0.1:9050"})
    assert prefs.value("downloads.concurrent") == 2 and load_settings()["network"]["proxy"].startswith("socks5")
    preset_id = prefs.savePreset({"label": "Talks", "kind": "video", "max_height": 720, "container": "mkv"})
    assert preset_id.startswith("user-")
    assert prefs.preset(preset_id)["container"] == "mkv"
    assert any(p["code"] == preset_id for p in prefs.presets)
    prefs.saveSettings({"downloads.preset": preset_id})
    prefs.deletePreset(preset_id)
    assert prefs.value("downloads.preset") == "video-best-mp4"
    prefs.saveSettings({"downloads.concurrent": 99})  # invalid: dropped on reload
    assert prefs.value("downloads.concurrent") == 0
    prefs.shutdown()


def test_refused_youtube_sign_in_is_marked_for_signing_in_again(qapp, context, tmp_path):
    """When YouTube won't open Watch later with the new cookies, the sign-in isn't trusted."""
    signins = SignInsController(context, runner=fake_check(1, "[youtube:tab] WL: The playlist does not exist."))
    signed, notices = [], []
    signins.signedIn.connect(signed.append)
    signins.notice.connect(notices.append)
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(format_netscape(youtube_cookies()), encoding="utf-8")
    signins.importFile("youtube", str(cookie_file))
    assert wait_for(qapp, lambda: any("didn't accept" in notice for notice in notices))
    assert signed == [] and context.store.account_for_site("youtube")["status"] == "expired"
    row = next(signins.model.get(i) for i in range(signins.model.count) if signins.model.get(i)["siteKey"] == "youtube")
    assert row["status"] == "expired" and row["library"] == []
    signins.shutdown()
