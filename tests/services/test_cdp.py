"""DevTools over the browser's own pipe: no port, so no other program on the PC can reach the browser."""

import sys
from pathlib import Path

import pytest

from gfgmd.core.platform import ProcessGroup
from gfgmd.services.cdp import CdpError, CdpPipe

FAKE_BROWSER = Path(__file__).resolve().parents[1] / "fakes" / "fake_browser.py"

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the debugging pipe is set up for Windows")


def run_browser(argv: list[str], pipe: CdpPipe) -> ProcessGroup:
    group = ProcessGroup()
    group.launch([*argv, *pipe.browser_args()], capture=False, inherit=pipe.child_handles())
    pipe.started()
    return group


def test_cookies_are_read_over_the_pipe_and_the_browser_closes() -> None:
    pipe = CdpPipe(timeout=10)
    group = run_browser([sys.executable, str(FAKE_BROWSER)], pipe)
    try:
        assert pipe.call("Storage.getCookies")["cookies"][0]["name"] == "SID"  # past the unrelated event
        pipe.send_only("Browser.close")
        assert group.process is not None and group.process.wait(timeout=10) == 0
    finally:
        group.kill()
        group.close()
        pipe.close()


def test_a_browser_that_ends_without_answering_says_so() -> None:
    """Another window of the same sign-in takes the profile, so the new browser ends at once."""
    pipe = CdpPipe(timeout=10)
    group = run_browser([sys.executable, "-c", "pass"], pipe)
    try:
        with pytest.raises(CdpError, match="closed before answering"):
            pipe.call("Storage.getCookies")
    finally:
        group.kill()
        group.close()
        pipe.close()
