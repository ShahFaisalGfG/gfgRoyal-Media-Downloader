"""The download tools: what the window says about installs, update checks, and missing programs."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gfgmd.controllers import tools_ctrl
from gfgmd.controllers.tools_ctrl import ToolsController
from gfgmd.core.tool_install import ToolDownloadError, ToolInstallCancelled, ToolStartError, ToolVerifyError
from gfgmd.core.tools import ToolsMissing
from gfgmd.services import tool_manager
from gfgmd.services.tool_manager import ToolManager


class FakeManager:
    """Stands in for ToolManager: reports missing programs, and installs or fails as told."""

    def __init__(self, missing: tuple[str, ...] = (), failure: BaseException | None = None,
                 check_failure: BaseException | None = None) -> None:
        self._missing = list(missing)
        self.failure = failure
        self.check_failure = check_failure
        self.tools_root = Path(".")

    def missing(self) -> list[str]:
        return list(self._missing)

    def status(self) -> list[dict]:
        return []

    def install(self, names, progress, cancel) -> list[str]:
        progress("Deno: Downloading", 5, 10)
        if self.failure is not None:
            raise self.failure
        self._missing = []
        return ["deno"]

    def check_updates(self) -> list[str]:
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


def test_tool_versions_read_plainly() -> None:
    from gfgmd.controllers.tools_ctrl import plain_version
    assert plain_version("n7.1-20-g4f1f2d7c09-20241001") == "7.1"
    assert plain_version("N-117690-gb2f3fa6d76-20241001") == "from 1 Oct 2024"
    assert plain_version("2026.10.26") == "2026.10.26" and plain_version("") == ""
