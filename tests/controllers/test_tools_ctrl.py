"""The download tools: what the window says about installs, update checks, and missing programs."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gfgmd.controllers import tools_ctrl
from gfgmd.controllers.tools_ctrl import ToolsController
from gfgmd.core.tool_install import ToolDownloadError, ToolInstallCancelled, ToolStartError, ToolVerifyError, packages
from gfgmd.core.tools import ToolsMissing
from gfgmd.services import tool_manager
from gfgmd.services.tool_manager import ToolManager


class FakeManager:
    """Stands in for ToolManager: reports missing programs, and installs or fails as told."""

    def __init__(self, missing: tuple[str, ...] = (), failure: BaseException | None = None,
                 check_failure: BaseException | None = None, extras: tuple[str, ...] = (),
                 extras_fail: tuple[str, ...] = ()) -> None:
        self._missing = list(missing)
        self._extras = list(extras)
        self.extras_fail = extras_fail
        self.asked: list[list[str]] = []
        self.failure = failure
        self.check_failure = check_failure
        self.tools_root = Path(".")
        self.is_metered = False
        self.checks = 0

    def hold_updates(self) -> bool:
        return self.is_metered

    def missing(self) -> list[str]:
        return list(self._missing)

    def missing_extras(self) -> list[str]:
        return list(self._extras)

    def status(self) -> list[dict]:
        return []

    def install(self, names, progress, cancel) -> list[str]:
        self.asked.append(list(names))
        progress("Deno: Downloading", 5, 10)
        if self.failure is not None:
            raise self.failure
        self._missing = []
        self._extras = [name for name in self._extras if name in self.extras_fail]
        return [name for name in names if name not in self.extras_fail] or ["deno"]

    def check_updates(self) -> list[str]:
        self.checks += 1
        if self.check_failure is not None:
            raise self.check_failure
        return ["yt-dlp", "ffmpeg"]


def settle(qapp, controller: ToolsController, timeout: float = 10.0) -> None:
    """Let the background task finish and its result reach the controller."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if not controller.busy and controller._runner.active == 0:
            return
        time.sleep(0.01)
    raise AssertionError("the tools task didn't finish")


@pytest.fixture
def make(qapp):
    made: list[ToolsController] = []

    def build(manager: FakeManager) -> tuple[ToolsController, list[str]]:
        controller = ToolsController(manager)  # type: ignore[arg-type]
        notices: list[str] = []
        controller.notice.connect(notices.append)
        made.append(controller)
        return controller, notices

    yield build
    for controller in made:
        controller.shutdown()


@pytest.mark.parametrize("failure, text", [
    (ToolDownloadError("https://github.com/x/SUMS answered HTTP 403"), tools_ctrl.INSTALL_OFFLINE),
    (ToolVerifyError("The download doesn't match its published checksum, so it was deleted"),
     tools_ctrl.INSTALL_UNSAFE),
    (ToolStartError("deno.exe from Deno didn't run on this PC", "Deno"),
     "Deno didn't start on this PC. Your antivirus may have blocked it."),
    (PermissionError(13, "Access is denied", r"C:\tools\.staging\deno"), tools_ctrl.INSTALL_SAVE),
    (RuntimeError("a bug"), tools_ctrl.INSTALL_FAILED),
])
def test_a_failed_install_says_what_to_do_not_what_broke(qapp, make, failure, text):
    controller, notices = make(FakeManager(missing=("deno",), failure=failure))
    controller.installMissing()
    settle(qapp, controller)
    assert controller.stage == text and notices == [text]
    assert str(failure) not in text


def test_cancelling_an_install_needs_no_toast(qapp, make):
    controller, notices = make(FakeManager(missing=("deno",), failure=ToolInstallCancelled("Download cancelled")))
    controller.installMissing()
    settle(qapp, controller)
    assert controller.stage == tools_ctrl.INSTALL_STOPPED and notices == []


def test_a_finished_install_says_the_tools_are_ready(qapp, make):
    controller, notices = make(FakeManager(missing=("deno",)))
    ready: list[bool] = []
    controller.toolsReady.connect(lambda: ready.append(True))
    controller.installMissing()
    settle(qapp, controller)
    assert controller.stage == "The download tools are ready." and ready == [True] and notices == []


def test_an_update_check_that_cant_connect_says_so(qapp, make):
    controller, _notices = make(FakeManager(check_failure=ToolDownloadError("Couldn't reach GitHub: [Errno 11001]")))
    controller.checkUpdates()
    settle(qapp, controller)
    assert controller.stage == tools_ctrl.CHECK_OFFLINE


def test_an_update_check_names_the_programs(qapp, make):
    controller, _notices = make(FakeManager())
    controller.checkUpdates()
    settle(qapp, controller)
    assert controller.stage == "New versions are available: yt-dlp, FFmpeg. Click Update tools."


def test_partly_missing_tools_are_told_apart_from_a_first_run(qapp, make):
    first_run, _ = make(FakeManager(missing=("yt-dlp", "ffmpeg", "ffprobe", "deno")))
    assert not first_run.ready and not first_run.partlyMissing
    damaged, _ = make(FakeManager(missing=("ffprobe",)))
    assert not damaged.ready and damaged.partlyMissing


def test_a_first_run_gets_the_extras_too_and_a_failed_extra_leaves_the_app_ready(qapp, make):
    """gallery-dl and spotDL come with the first download; one that fails is named, and downloads still work."""
    manager = FakeManager(missing=("yt-dlp", "deno"), extras=("gallery-dl", "spotdl"), extras_fail=("spotdl",))
    controller, notices = make(manager)
    assert "gallery-dl (saving pictures from posts) and spotDL" in controller.extrasNote
    controller.installMissing()
    settle(qapp, controller)
    assert manager.asked == [["yt-dlp", "deno", "gallery-dl", "spotdl"]]
    failed = "spotDL (reading long Spotify playlists) couldn't be installed. Click Update tools in Preferences > Tools to try again."
    assert controller.stage == "The download tools are ready. " + failed and notices == [failed]
    assert controller.ready and controller.extrasNote.startswith("spotDL (reading long Spotify playlists) is not installed")


def test_a_missing_extra_alone_is_installed_on_its_own(qapp, make):
    manager = FakeManager(extras=("gallery-dl",))
    controller, _notices = make(manager)
    assert controller.ready
    controller.installMissing()
    settle(qapp, controller)
    assert manager.asked == [["gallery-dl"]] and controller.extrasNote == ""


def _size(*tools: str) -> str:
    return f"about {sum(package.approx_mb for package in packages() if package.tool in tools):,} MB"


def test_downloads_offers_the_missing_extras_once_the_app_is_ready(qapp, make, monkeypatch):
    """An app set up before gallery-dl and spotDL existed offers them on Downloads, sized for just them."""
    monkeypatch.setattr(tools_ctrl.sys, "platform", "win32")
    manager = FakeManager(extras=("gallery-dl", "spotdl"))
    controller, _notices = make(manager)
    assert controller.ready and controller.offerExtras
    assert controller.downloadSize == _size("gallery-dl", "spotdl")
    assert controller.extrasTitle == "Get the picture and Spotify tools"
    assert controller.extrasOffer == (
        "Saving pictures from posts needs gallery-dl, and reading long Spotify playlists needs spotDL "
        f"({_size('gallery-dl', 'spotdl')}). They come from their official sources, are checked for safety, "
        "and stay up to date on their own. Other downloads work without them.")
    controller.installMissing()
    settle(qapp, controller)
    assert manager.asked == [["gallery-dl", "spotdl"]] and not controller.offerExtras


def test_not_now_a_first_run_and_other_tool_sources_dont_offer_the_extras(qapp, make, monkeypatch):
    monkeypatch.setattr(tools_ctrl.sys, "platform", "win32")
    later, _ = make(FakeManager(extras=("spotdl",)))
    assert later.offerExtras and later.extrasTitle == "Get the Spotify tool"
    assert later.extrasOffer.startswith(f"Reading long Spotify playlists needs spotDL ({_size('spotdl')}). It comes")
    later.extrasLater()
    assert not later.offerExtras and later.extrasNote  # Preferences > Tools still names it
    first_run, _ = make(FakeManager(missing=("yt-dlp", "deno"), extras=("spotdl",)))
    assert not first_run.offerExtras  # the first-run card gets them with the rest
    assert first_run.downloadSize == _size("yt-dlp", "deno", "spotdl")
    monkeypatch.setattr(tools_ctrl, "load_settings", lambda: {"tools": {"source": "path"}})
    on_path, _ = make(FakeManager(extras=("gallery-dl",)))
    assert not on_path.offerExtras  # Download tools would save copies the app doesn't use


def test_ffprobe_is_shown_as_part_of_ffmpeg():
    row = {"version": "n7.1", "path": "C:/tools/x.exe", "canRollBack": False}
    rows = [{**row, "name": "yt-dlp", "label": "yt-dlp", "origin": "managed"},
            {**row, "name": "ffmpeg", "label": "FFmpeg", "origin": "managed"},
            {**row, "name": "ffprobe", "label": "FFmpeg", "origin": "managed"},
            {**row, "name": "deno", "label": "Deno", "origin": "path"}]
    assert [r["name"] for r in tools_ctrl._merge_ffprobe(rows)] == ["yt-dlp", "ffmpeg", "deno"]
    rows[2] = {**rows[2], "origin": "missing", "version": "", "path": ""}
    ffmpeg = next(r for r in tools_ctrl._merge_ffprobe(rows) if r["name"] == "ffmpeg")
    assert ffmpeg["origin"] == "missing" and ffmpeg["version"] == ""


def test_missing_tools_are_described_without_program_names():
    error = ToolsMissing(["yt-dlp", "ffprobe"])
    assert str(error) == "The download tools aren't installed yet." and error.missing == ["yt-dlp", "ffprobe"]


def test_a_failed_extra_doesnt_stop_the_required_tools(tmp_path, monkeypatch):
    """ToolManager logs an extra that fails and installs the rest; a required program's failure stops it."""
    done: list[str] = []

    def fake_install(package, root, progress, cancel, channel="stable"):
        if package.tool in ("gallery-dl", "deno") and package.tool in failing:
            raise ToolDownloadError(f"{package.label} is unreachable")
        done.append(package.tool)
        return {}

    monkeypatch.setattr(tool_manager, "install", fake_install)
    monkeypatch.setattr(tool_manager, "remove_unused", lambda root: None)
    manager = ToolManager(SimpleNamespace(settings=lambda: {}, tools_root=tmp_path))  # type: ignore[arg-type]
    failing = {"gallery-dl"}
    assert manager.install(["yt-dlp", "gallery-dl", "spotdl"], lambda *args: None, threading.Event()) == ["yt-dlp", "spotdl"]
    failing = {"deno"}
    with pytest.raises(ToolDownloadError):
        manager.install(["deno", "gallery-dl"], lambda *args: None, threading.Event())


class TestUpdateCheck:
    @pytest.fixture
    def manager(self, tmp_path, monkeypatch) -> ToolManager:
        monkeypatch.setattr(tool_manager, "managed_tools",
                            lambda root: {"yt-dlp": "a", "ffmpeg": "b", "ffprobe": "c", "deno": "d"})
        return ToolManager(SimpleNamespace(settings=lambda: {}, tools_root=tmp_path))  # type: ignore[arg-type]

    def test_offline_is_an_error_not_up_to_date(self, manager, monkeypatch):
        def offline(package, root):
            raise ToolDownloadError("Couldn't reach GitHub: getaddrinfo failed")

        monkeypatch.setattr(tool_manager, "update_available", offline)
        with pytest.raises(ToolDownloadError):
            manager.check_updates()

    def test_one_reachable_program_is_enough(self, manager, monkeypatch):
        def some(package, root):
            if package.tool == "deno":
                raise ToolDownloadError("Couldn't reach GitHub: timed out")
            return package.tool == "yt-dlp"

        monkeypatch.setattr(tool_manager, "update_available", some)
        assert manager.check_updates() == ["yt-dlp"]


def test_automatic_tool_updates_wait_on_a_metered_connection(qapp, make):
    """Nothing is checked or downloaded on its own while metered; it looks again in half an hour, and
    Update tools still installs at once."""
    manager = FakeManager()
    manager.is_metered = True
    controller, _notices = make(manager)
    controller._auto_update()
    assert manager.checks == 0 and controller.stage == tools_ctrl.METERED_WAIT
    assert controller._daily.interval() == tools_ctrl.METERED_RETRY_MS
    controller.updateAll()
    settle(qapp, controller)
    assert controller.stage == "The download tools are ready."
    manager.is_metered = False
    controller._auto_update()
    settle(qapp, controller)
    assert manager.checks == 1 and controller._daily.interval() == tools_ctrl.DAILY_MS


def test_yt_dlp_waits_for_an_unmetered_connection_after_a_failure(tmp_path, monkeypatch):
    """A download's automatic yt-dlp update skips a metered connection; a forced one goes ahead."""
    asked: list[str] = []
    monkeypatch.setattr(tool_manager, "managed_tools", lambda root: {"yt-dlp": "a"})
    monkeypatch.setattr(tool_manager, "update_available", lambda package, root: asked.append(package.tool) or False)
    metered = ToolManager(SimpleNamespace(settings=lambda: {}, tools_root=tmp_path),  # type: ignore[arg-type]
                          metered=lambda: True)
    assert not metered.update_ytdlp() and asked == []
    assert not metered.update_ytdlp(force=True) and asked == ["yt-dlp"]
    free = ToolManager(SimpleNamespace(settings=lambda: {}, tools_root=tmp_path),  # type: ignore[arg-type]
                       metered=lambda: False)
    assert not free.update_ytdlp() and asked == ["yt-dlp", "yt-dlp"]
    allowed = ToolManager(SimpleNamespace(settings=lambda: {"updates": {"allow_metered": True}},  # type: ignore[arg-type]
                                          tools_root=tmp_path), metered=lambda: True)
    assert metered.hold_updates() and not allowed.hold_updates()
    assert not allowed.update_ytdlp() and asked == ["yt-dlp", "yt-dlp", "yt-dlp"]


def test_managed_versions_come_from_the_manifest_and_others_run(tmp_path, monkeypatch):
    """A finished install's versions show at once: managed copies aren't started again, and a program
    from PATH is; a missing extra doesn't hide the programs that were found."""
    tools_root = tmp_path / "tools"
    for name in ("yt-dlp", "deno"):
        (tools_root / name / "v1").mkdir(parents=True)
        (tools_root / name / "v1" / f"{name}.exe").write_bytes(b"")
    (tools_root / "manifest.json").write_text(
        '{"yt-dlp": {"path": "yt-dlp/v1/yt-dlp.exe", "version": "2026.11.23"},'
        ' "deno": {"path": "deno/v1/deno.exe", "version": "2.9.8", "previous": {"path": "deno/v0/deno.exe"}}}',
        encoding="utf-8")
    ffmpeg = str(tmp_path / "bin" / "ffmpeg.exe")
    monkeypatch.setattr(tool_manager, "path_tools", lambda: {"ffmpeg": ffmpeg})
    started: list[str] = []
    monkeypatch.setattr(tool_manager, "tool_version", lambda name, path: started.append(name) or "n7.1")
    found = {**tool_manager.managed_tools(tools_root), "ffmpeg": ffmpeg}
    manager = ToolManager(SimpleNamespace(settings=lambda: {}, tools_root=tools_root,  # type: ignore[arg-type]
                                          tool_paths=lambda: found))
    rows = {row["name"]: row for row in manager.status()}
    assert started == ["ffmpeg"]
    assert (rows["yt-dlp"]["version"], rows["yt-dlp"]["origin"]) == ("2026.11.23", "managed")
    assert rows["deno"]["canRollBack"] and not rows["yt-dlp"]["canRollBack"]
    assert (rows["ffmpeg"]["version"], rows["ffmpeg"]["origin"]) == ("n7.1", "path")
    assert rows["spotdl"]["origin"] == "missing" and rows["spotdl"]["version"] == ""


def test_tool_versions_read_plainly() -> None:
    from gfgmd.controllers.tools_ctrl import plain_version
    assert plain_version("n7.1-20-g4f1f2d7c09-20241001") == "7.1"
    assert plain_version("N-117690-gb2f3fa6d76-20241001") == "from 1 Oct 2024"
    assert plain_version("2026.10.26") == "2026.10.26" and plain_version("") == ""
