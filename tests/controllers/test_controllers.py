"""Analyze, library, subscriptions, sign-ins, preferences, and tools controllers."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd.controllers import subscriptions_ctrl
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
        assert controller.hasResult and controller.isPlaylist  # a list's choices show while its videos arrive
        assert wait_for(qapp, lambda: controller.ready)
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
        assert wait_for(qapp, lambda: controller.ready)
    assert len(calls) == 2 and controller.error == ""
    controller.shutdown()


def counting_runner(prefix, calls, hold=None):
    """fake_runner that notes each command, and waits on `hold` (an Event) before running when given."""
    real = fake_runner(prefix)

    def run(command, on_line, stop=None, env=None, cwd=None, max_line_bytes=1024 * 1024):
        calls.append(command)
        if hold is not None:
            hold.wait(10)
        return real(command, on_line, stop, env, cwd, max_line_bytes)
    return run


def test_a_videos_subtitles_list_the_creators_then_automatic_then_translations(qapp, context, paused_queue,
                                                                             fake_ytdlp, tmp_path):
    controller = AnalyzeController(context, paused_queue)
    with patch.object(analyze_module, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert wait_for(qapp, lambda: controller.ready)
    tracks = [(track["code"], track["kind"]) for track in controller.subtitleTracks]
    assert tracks == [("en", "creator"), ("de-DE", "creator"), ("en-orig", "automatic"), ("fr", "translated"),
                      ("ur", "translated")]
    assert controller.subtitleTracks[2]["name"] == "English (automatic)"
    controller.shutdown()


def test_a_link_read_once_opens_again_at_once(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    """Pasting reads ahead; opening Download options then, or again later, reads nothing more."""
    calls: list[list[str]] = []
    controller = AnalyzeController(context, paused_queue)
    runner = counting_runner(fake_ytdlp + ["--paths", str(tmp_path)], calls)
    with patch.object(analyze_module, "run_to_completion", runner):
        controller.prefetch("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert controller.title == "" and not controller.busy  # nothing shows until Download options open
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert wait_for(qapp, lambda: controller.ready) and controller.title == "Clip"
        controller.clear()
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert controller.ready and controller.title == "Clip"
    assert len(calls) == 1
    controller.shutdown()


def test_a_read_that_ends_after_another_link_opened_only_fills_the_cache(qapp, context, paused_queue, fake_ytdlp,
                                                                          tmp_path):
    hold = threading.Event()
    controller = AnalyzeController(context, paused_queue)
    runner = counting_runner(fake_ytdlp + ["--paths", str(tmp_path)], [], hold)
    with patch.object(analyze_module, "run_to_completion", runner):
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        controller.analyze("https://www.youtube.com/playlist?list=PLfake")
        hold.set()
        assert wait_for(qapp, lambda: controller.ready)
        time.sleep(0.5)
        qapp.processEvents()
        assert controller.title == "Fake List" and controller.error == "" and controller.isPlaylist
    controller.shutdown()


def test_the_quick_title_shows_while_the_details_are_read(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    hold = threading.Event()
    asked: list[str] = []

    def oembed(url):
        asked.append(url)
        return {"title": "Quick Clip", "author_name": "Channel", "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg"}

    controller = AnalyzeController(context, paused_queue, quick_fetch=oembed)
    runner = counting_runner(fake_ytdlp + ["--paths", str(tmp_path)], [], hold)
    with patch.object(analyze_module, "run_to_completion", runner):
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert wait_for(qapp, lambda: controller.title == "Quick Clip")
        assert controller.busy and controller.uploader == "Channel" and controller.thumbnail.startswith("https://")
        assert asked[0].startswith("https://www.youtube.com/oembed?") and not controller.ready
        hold.set()
        assert wait_for(qapp, lambda: controller.ready) and controller.title == "Clip"
    controller.shutdown()


def test_a_video_inside_a_playlist_reads_the_video_or_the_list(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    calls: list[list[str]] = []
    controller = AnalyzeController(context, paused_queue)
    link = "https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLfake"
    runner = counting_runner(fake_ytdlp + ["--paths", str(tmp_path)], calls)
    with patch.object(analyze_module, "run_to_completion", runner):
        controller.analyze(link)
        assert wait_for(qapp, lambda: controller.ready)
        assert (controller.inPlaylist, controller.scope, controller.title) == (True, "video", "Clip")
        assert controller.link == link  # kept as given, for switching to the playlist
        assert "--no-playlist" in calls[-1] and calls[-1][-1] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
        controller.analyze(link, "playlist")
        assert wait_for(qapp, lambda: controller.ready)
        assert (controller.scope, controller.title, controller.entries.totalCount) == ("playlist", "Fake List", 2)
        assert "--lazy-playlist" in calls[-1]
    controller.shutdown()


def test_reading_a_link_goes_through_the_proxy(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    settings = load_settings()
    settings["network"].update({"proxy": "http://127.0.0.1:8080", "force_ipv4": True})
    save_settings(settings)
    calls: list[list[str]] = []
    controller = AnalyzeController(context, paused_queue)
    runner = counting_runner(fake_ytdlp + ["--paths", str(tmp_path)], calls)
    with patch.object(analyze_module, "run_to_completion", runner):
        controller.analyze("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert wait_for(qapp, lambda: controller.ready)
    assert "--force-ipv4" in calls[0] and calls[0][calls[0].index("--proxy") + 1] == "http://127.0.0.1:8080"
    controller.shutdown()


def test_several_links_share_one_set_of_choices(qapp, context, paused_queue):
    controller = AnalyzeController(context, paused_queue)
    controller.showLinks(["https://fake.test/ok", "https://fake.test/flaky"])
    assert (controller.linkCount, controller.title, controller.ready) == (2, "2 links", True)
    assert controller.addToQueue({"kind": "audio", "audio_format": "flac"})
    jobs = context.store.jobs()
    assert [json.loads(job["options_json"])["audio_format"] for job in jobs] == ["flac", "flac"]
    assert controller.linkCount == 0
    controller.shutdown()


def test_the_link_box_knows_a_link_by_its_form(qapp):
    """The Download button inside the link box shows for these; nothing is fetched to decide."""
    from gfgmd.controllers.app_ctrl import AppController
    app = AppController()
    assert app.validLink("https://www.youtube.com/watch?v=aaaaaaaaaaa") and app.validLink("youtu.be/aaaaaaaaaaa")
    assert not app.validLink("hello there") and not app.validLink("ftp://example.com/x") and not app.validLink("")


def test_controls_stop_moving_when_windows_animations_are_off(qapp):
    """Theme.motion follows Windows' Animation effects, read again when a window regains focus."""
    from gfgmd.controllers import app_ctrl
    with patch.object(app_ctrl, "_system_animations", return_value=True):
        app = app_ctrl.AppController()
    assert app.animations
    changes = []
    app.animationsChanged.connect(lambda: changes.append(app.animations))
    with patch.object(app_ctrl, "_system_animations", return_value=False):
        app.detectTheme()
        app.detectTheme()
    assert changes == [False] and not app.animations


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
    assert library.total == 1 and library.model.get(0)["missing"] is False and library.model.get(0)["format"] == "MP4"
    library.setFilters("", "audio", "")
    assert library.model.get(0)["missing"] is True
    with patch.object(recycle_module, "to_recycle_bin", return_value=True) as recycle:
        library.setFilters("", "", "")
        lecture = next(library.model.get(i) for i in range(library.model.count) if library.model.get(i)["title"] == "Lecture one")
        library.deleteFiles([lecture["historyId"]])
    recycle.assert_called_once_with([str(keep), str(tmp_path / "keep.en.srt")])
    assert library.total == 1


def test_library_keeps_a_file_windows_could_not_move(qapp, context, tmp_path):
    """The players let go first; a file still held elsewhere stays listed and the notice names it."""
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    ids = []
    for path in (first, second):
        path.write_bytes(b"v")
        ids.append(context.store.add_history(str(path), title=path.stem, kind="video", site="youtube"))
    released: list[list[str]] = []
    library = LibraryController(context, release_files=released.append)
    notices: list[str] = []
    library.notice.connect(notices.append)

    def held_second(paths: list[str]) -> bool:
        if str(second) in paths:
            return False
        for path in paths:
            Path(path).unlink()
        return True

    with patch.object(recycle_module, "to_recycle_bin", side_effect=held_second):
        library.deleteFiles(ids)
    assert released == [[str(first), str(second)]]
    assert not first.exists() and second.exists()
    assert [record["filepath"] for record in context.store.history()] == [str(second)]
    assert notices == ["Couldn't move \"second.mp4\" to the Recycle Bin. Close it in other programs and try again."]


def test_library_recycle_bin_removes_the_folders_it_empties(qapp, context, tmp_path):
    """A channel tab's last file takes its folder, and the channel's once its other tab goes; a file
    saved before its download folder was recorded finds today's; the download folder, and a folder
    outside every download folder, stay."""
    root = context.download_root("video")
    videos, shorts = root / "Channel" / "Videos", root / "Channel" / "Shorts"
    elsewhere = tmp_path / "Elsewhere" / "List"
    ids = {}
    for folder, name, recorded in ((videos, "A", str(root)), (shorts, "B", ""), (elsewhere, "C", "")):
        folder.mkdir(parents=True)
        path = folder / f"{name}.mp4"
        path.write_bytes(b"v")
        (folder / f"{name}.en.srt").write_text("1")
        ids[name] = context.store.add_history(str(path), title=name, kind="video", site="youtube",
                                              group_key=str(folder).casefold(), group_title=name, output_root=recorded)
    library = LibraryController(context)

    def moved_out(paths: list[str]) -> bool:
        for path in paths:
            Path(path).unlink()
        return True

    with patch.object(recycle_module, "to_recycle_bin", side_effect=moved_out):
        library.deleteFiles([ids["A"]])
        assert not videos.exists() and shorts.is_dir()  # the channel still holds its Shorts
        library.deleteFiles([ids["B"], ids["C"]])
    assert not (root / "Channel").exists() and root.is_dir()
    assert elsewhere.is_dir() and not any(elsewhere.iterdir()) and library.total == 0


def test_library_groups_a_playlists_files_in_order(qapp, context):
    """A playlist's folder is one row that opens into its files in the playlist's order; singles stand alone."""
    root = context.download_root("video")
    folder = root / "Road Trip"
    folder.mkdir(parents=True)
    paths = []
    for position, name in ((2, "Second"), (1, "First"), (3, "Third")):
        path = folder / f"{name}.mp4"
        path.write_bytes(b"v")
        paths.append(path)
        context.store.add_history(str(path), title=name, kind="video", site="youtube", position=position,
                                  group_key=str(folder).casefold(), group_title="Road Trip", finished=100.0 + position)
    single = root / "Talk.mp4"
    single.write_bytes(b"v")
    context.store.add_history(str(single), title="Talk", kind="video", site="youtube", group_key="", finished=50.0)
    library = LibraryController(context)
    rows = [library.model.get(i) for i in range(library.model.count)]
    assert [(row["rowType"], row["title"]) for row in rows] == [("group", "Road Trip"), ("file", "Talk")]
    assert rows[0]["countText"] == "3 videos" and rows[0]["fileCount"] == 3 and library.total == 4
    key = rows[0]["groupKey"]
    library.setExpanded(key, True)
    rows = [library.model.get(i) for i in range(library.model.count)]
    assert [(row["title"], row["number"], row["inGroup"]) for row in rows] == [
        ("Road Trip", 0, False), ("First", 1, True), ("Second", 2, True), ("Third", 3, True), ("Talk", 0, False)]
    assert library.groupPaths(key) == [str(folder / "First.mp4"), str(folder / "Second.mp4"), str(folder / "Third.mp4")]
    assert len(library.groupIds(key)) == 3
    # A search lists the group's matching files, open.
    library.setExpanded(key, False)
    library.setFilters("third", "", "")
    rows = [library.model.get(i) for i in range(library.model.count)]
    assert [(row["rowType"], row["title"]) for row in rows] == [("group", "Road Trip"), ("file", "Third")]


def test_library_works_out_the_groups_of_older_files(qapp, context):
    """Files saved before groups (or by 1.0.0) are grouped by their folder under the download folder."""
    root = context.download_root("video")
    channel = root / "Some Channel" / "Videos"
    channel.mkdir(parents=True)
    clip, loose = channel / "Clip.mp4", root / "Loose.mp4"
    for path in (clip, loose):
        path.write_bytes(b"v")
    clip_id = context.store.add_history(str(clip), title="Clip", kind="video")
    loose_id = context.store.add_history(str(loose), title="Loose", kind="video")
    assert context.store.history_record(clip_id)["group_key"] is None
    LibraryController(context)
    assert context.store.history_record(clip_id)["group_title"] == "Some Channel · Videos"
    assert context.store.history_record(loose_id)["group_key"] == ""


def test_library_select_all_and_play_the_selection(qapp, context, tmp_path):
    """Select all takes every file the filters show; Play takes the picked files still there, newest first."""
    older, newer, gone = tmp_path / "older.mp3", tmp_path / "newer.mp4", tmp_path / "gone.mp3"
    older.write_bytes(b"a")
    newer.write_bytes(b"v")
    ids = [context.store.add_history(str(older), title="Older", kind="audio", finished=100.0),
           context.store.add_history(str(newer), title="Newer", kind="video", finished=200.0),
           context.store.add_history(str(gone), title="Gone", kind="audio", finished=300.0)]
    library = LibraryController(context)
    assert sorted(library.allIds()) == sorted(ids)
    library.setFilters("", "audio", "")
    assert sorted(library.allIds()) == sorted([ids[0], ids[2]])
    assert library.pathsOf(ids) == [str(newer), str(older)]


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


def test_a_playlist_subscription_reads_the_whole_list(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    """Its first videos downloaded before, a playlist still learns its name, and a video at its end
    (where new ones are added) is found: playlists are read whole, not stopped at a known video."""
    from gfgmd.controllers.queue_ctrl import base_options
    subs = SubscriptionsController(context, paused_queue, Notifier(lambda: None, lambda p: None))
    url = "https://www.youtube.com/playlist?list=PLfake"
    source = source_from_url(url)
    archive = archive_path(Path(load_settings()["downloads"]["folder"]), source, base_options(load_settings()).profile)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text("youtube nnnnnnnnnn3\nyoutube nnnnnnnnnn1\n", encoding="utf-8")
    with patch.object(subscriptions_ctrl, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        assert subs.add(url, {}, 6, False, True)
        assert wait_for(qapp, lambda: subs.model.count == 1 and "Watching" in subs.model.get(0)["resultText"])
        assert subs.model.get(0)["title"] == "Fake Channel - Videos"  # its own name, not its link
        archive.write_text("youtube nnnnnnnnnn3\nyoutube nnnnnnnnnn1\n", encoding="utf-8")  # "ooooooooooo" is new
        subs.checkNow(context.store.subscriptions()[0]["id"])
        assert wait_for(qapp, lambda: context.store.jobs() != [])
    job = context.store.jobs()[0]
    assert job["url"] == "https://www.youtube.com/watch?v=ooooooooooo" and job["folder"] == "Fake Channel - Videos"
    subs.shutdown()


def test_importing_twice_keeps_existing_subscriptions_as_they_are(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    """A second import doesn't count a watched channel again or start it over (which would mark its new
    uploads as downloaded)."""
    subs = SubscriptionsController(context, paused_queue, Notifier(lambda: None, lambda p: None))
    notices = []
    subs.notice.connect(notices.append)
    takeout = "Channel Id,Channel Url,Channel Title\nUCfake,http://www.youtube.com/channel/UCfake,Fake\n"
    with patch.object(subscriptions_ctrl, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        assert subs.importTakeout(takeout) == 1
        assert wait_for(qapp, lambda: subs.model.count == 1 and "Watching" in subs.model.get(0)["resultText"])
        assert subs.importTakeout(takeout) == 0
    assert notices[-1] == "Subscribed to 0 channels. 1 was already in your list."
    assert len(context.store.subscriptions()) == 1
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


def test_subscribe_says_why_a_link_cant_be_used(qapp, context, paused_queue, fake_ytdlp, tmp_path):
    """Not a link, a single video, or one already watched: each is named before anything is added."""
    subs = SubscriptionsController(context, paused_queue, Notifier(lambda: None, lambda p: None))
    assert "https://" in subs.linkProblem("not-a-link")
    assert "not a single video" in subs.linkProblem("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert subs.linkProblem("www.youtube.com/@fake/videos") == ""  # typed without https:// is fine
    with patch.object(subscriptions_ctrl, "run_to_completion", fake_runner(fake_ytdlp + ["--paths", str(tmp_path)])):
        assert subs.add("https://www.youtube.com/@fake/videos", {}, 6, False, True)
        assert wait_for(qapp, lambda: subs.model.count == 1)
    assert subs.linkProblem("https://www.youtube.com/@fake/videos") == "You're already subscribed to this."
    subs.shutdown()  # its check thread must not outlive it and signal a deleted controller later


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


# ── Tray ──────────────────────────────────────────────────────────────────

def test_closing_to_the_tray_says_so_once(qapp, monkeypatch):
    """The first close to the tray says the app goes on running there; later closes, or with
    notifications off, say nothing."""
    shown: list[str] = []
    notifier = Notifier(lambda: None, lambda path: None)
    monkeypatch.setattr(notifier, "notify", lambda title, body, path="": shown.append(title))
    settings = get_default_settings()
    settings["notifications"]["enabled"] = False
    save_settings(settings)
    notifier.tell_once_in_tray()
    assert shown == [] and not load_settings()["tray"]["told_running"]
    settings["notifications"]["enabled"] = True
    save_settings(settings)
    notifier.tell_once_in_tray()
    notifier.tell_once_in_tray()
    assert len(shown) == 1 and "still running" in shown[0] and load_settings()["tray"]["told_running"]


# ── Preferences ───────────────────────────────────────────────────────────

def test_preferences_save(qapp, context):
    prefs = PrefsController(context)
    prefs.saveSettings({"downloads.concurrent": 2, "network.proxy": "socks5://127.0.0.1:9050"})
    assert prefs.value("downloads.concurrent") == 2 and load_settings()["network"]["proxy"].startswith("socks5")
    prefs.saveSettings({"downloads.kind": "audio", "downloads.smart_mode": False, "downloads.playlist_links": "video"})
    assert (prefs.value("downloads.kind"), prefs.value("downloads.smart_mode")) == ("audio", False)
    assert [option["code"] for option in prefs.options["playlistLinks"]] == ["ask", "video", "playlist"]
    settings = load_settings()
    settings["downloads"]["playlist_links"] = "playlist"
    save_settings(settings)  # saved elsewhere in the app, as the "video or playlist" answer is
    revision = prefs.revision
    prefs.reload()
    assert prefs.value("downloads.playlist_links") == "playlist" and prefs.revision == revision + 1
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


def test_every_row_value_is_a_model_role(context, tmp_path):
    """A value missing from a model's roles never reaches QML, and a delegate requiring it isn't created."""
    from gfgmd.controllers import library_ctrl, queue_rows

    clip = tmp_path / "Clip (720p).mp4"
    clip.write_bytes(b"v")
    context.store.add_history(str(clip), title="Clip", kind="video", site="youtube")
    record = context.store.history()[0]
    assert set(library_ctrl._row(record, "YouTube")) == set(library_ctrl.ROLES)
    assert set(library_ctrl._group_row("k", [record], "YouTube", True)) == set(library_ctrl.ROLES)
    job_id = context.store.add_job("https://youtu.be/x", "playlist", "x", "youtube", {"kind": "video"}, str(tmp_path),
                                   items=[{"id": "a", "title": "A"}, {"id": "b", "title": "B"}])
    job = context.store.job(job_id)
    assert set(queue_rows.job_row(job, "YouTube", "", {}, True, "video")) == set(queue_rows.ROLES)
    item = context.store.job_items(job_id)[0]
    assert set(queue_rows.entry_row(job, item, 1, "video", "", None)) == set(queue_rows.ROLES)
