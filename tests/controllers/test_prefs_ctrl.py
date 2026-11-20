"""Preferences: the "Optimize for this PC" speed test reports in plain words, never raw errors."""

import time
from pathlib import Path

import pytest

from gfgmd.controllers import prefs_ctrl
from gfgmd.controllers.prefs_ctrl import PrefsController
from gfgmd.core.tools import ToolSet, ToolsMissing
from gfgmd.services.context import AppContext
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")
VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.fixture
def context(tmp_path: Path, monkeypatch):
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    save_settings(get_default_settings())
    yield context
    context.close()


@pytest.fixture
def prefs(qapp, context):
    controller = PrefsController(context)
    yield controller
    controller.shutdown()


def finish(qapp, prefs: PrefsController, url: str) -> str:
    """Start the speed test and wait for its message."""
    messages: list[str] = []
    prefs.optimizeFinished.connect(messages.append)
    prefs.startOptimize(url)
    deadline = time.monotonic() + 10
    while not messages and time.monotonic() < deadline:
        qapp.processEvents()
    assert messages, "the speed test never finished"
    return messages[0]


def test_a_bad_link_asks_for_a_video(qapp, prefs):
    assert finish(qapp, prefs, "not a link") == "Paste a link to one video to test with."


def test_missing_tools_point_to_the_tools_section(qapp, prefs, context, monkeypatch):
    def missing() -> ToolSet:
        raise ToolsMissing(["yt-dlp"])
    monkeypatch.setattr(context, "tools", missing)
    message = finish(qapp, prefs, VIDEO)
    assert "Tools section" in message and "yt-dlp" not in message


def test_the_fastest_parts_at_once_is_saved(qapp, prefs, monkeypatch):
    speeds = {4: 1.2 * 1024 * 1024, 8: 2.3 * 1024 * 1024, 16: 2.1 * 1024 * 1024}
    monkeypatch.setattr(prefs_ctrl, "measure", lambda *args: speeds)
    message = finish(qapp, prefs, VIDEO)
    assert message == ("Fastest here: 8 parts at once (4 parts: 1.2 MB/s, 8 parts: 2.3 MB/s, "
                       "16 parts: 2.1 MB/s). Saved.")
    assert load_settings()["downloads"]["fragments"] == 0  # Automatic is 8


def test_a_failed_test_hides_the_error_text(qapp, prefs, monkeypatch):
    def broken(*_args: object) -> dict[int, float]:
        raise OSError("[WinError 5] Access is denied: 'C:\\\\cache'")
    monkeypatch.setattr(prefs_ctrl, "measure", broken)
    message = finish(qapp, prefs, VIDEO)
    assert message.startswith("The speed test couldn't finish.") and "WinError" not in message
    assert not prefs.optimizing


def test_a_reset_keeps_the_note_of_the_installers_choices(qapp, prefs):
    """Otherwise the next start would apply the installer's choices again and undo the reset."""
    prefs.saveSettings({"install.connections": "OnlineLyrics=0;ToolUpdates=1;UpdateChecks=1",
                        "formats.lyrics_online": False})
    prefs.resetDefaults()
    saved = load_settings()
    assert saved["install"]["connections"] == "OnlineLyrics=0;ToolUpdates=1;UpdateChecks=1"
    assert saved["formats"]["lyrics_online"] is True
