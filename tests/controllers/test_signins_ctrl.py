"""The Sign-ins page's messages: plain words for the user, details only in the log."""

import time
from pathlib import Path

import pytest

from gfgmd.controllers.signins_ctrl import SignInsController
from gfgmd.core.auth import Cookie, format_netscape
from gfgmd.core.tools import ToolSet
from gfgmd.services.browser_signin import Browser
from gfgmd.services.context import AppContext
from gfgmd.utils.settings import get_default_settings, save_settings

FUTURE = int(time.time()) + 86400 * 30


@pytest.fixture
def signins(qapp, tmp_path: Path, monkeypatch):
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: ToolSet("yt-dlp", "ffmpeg", "ffprobe", "deno"))
    save_settings(get_default_settings())
    # The sign-in check "opens Watch later" and succeeds; no site is contacted.
    controller = SignInsController(context, runner=lambda command, on_line, stop: (0, False))
    notices: list[str] = []
    controller.notice.connect(notices.append)
    yield controller, notices
    controller.shutdown()
    context.close()


def wait_for(qapp, condition, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_a_file_that_cant_be_opened_is_described_without_its_path(signins, tmp_path):
    controller, notices = signins
    missing = tmp_path / "gone" / "cookies.txt"
    controller.importFile("youtube", str(missing))
    assert notices == ["That file couldn't be opened. Check that it still exists, then try again."]


def test_a_file_without_the_sites_sign_in_says_how_to_fix_it(signins, tmp_path):
    controller, notices = signins
    other = tmp_path / "cookies.txt"
    other.write_text(format_netscape([Cookie(".example.com", "/", "x", "y", expires=FUTURE)]), encoding="utf-8")
    controller.importFile("youtube", str(other))
    assert "no YouTube sign-in" in notices[-1] and "cookie" not in notices[-1].lower()


def test_an_unusable_site_address_gets_an_example(signins):
    controller, notices = signins
    assert controller.addSite("not a site at all") == ""
    assert notices == ["Type a site address, such as example.com, or paste a link from the site."]


def test_an_unreadable_browser_sign_in_names_the_browser_and_the_next_step(qapp, signins):
    controller, notices = signins
    # No sign-in window was ever opened, so the profile is missing and the read fails.
    controller._read_browser("youtube", Browser("chrome", "Google Chrome", "chrome.exe"))
    assert wait_for(qapp, lambda: bool(notices))
    assert notices == ["The app couldn't read your sign-in from Google Chrome. Close any windows opened for "
                       "this sign-in, then try again."]


def test_a_checked_sign_in_reads_naturally(qapp, signins, tmp_path):
    controller, notices = signins
    jar = tmp_path / "cookies.txt"
    jar.write_text(format_netscape([Cookie(".youtube.com", "/", "SAPISID", "s", expires=FUTURE)]), encoding="utf-8")
    controller.importFile("youtube", str(jar))
    assert wait_for(qapp, lambda: "Signed in to YouTube." in notices)
    row = next(controller.model.get(i) for i in range(controller.model.count)
               if controller.model.get(i)["siteKey"] == "youtube")
    assert row["methodText"] == "Imported file"
    assert row["detail"].startswith("Saved ") and "working (checked at " in row["detail"]
