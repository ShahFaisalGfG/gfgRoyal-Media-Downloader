"""The app's own web requests: through the Preferences proxy, and HTTPS only."""

import urllib.error
import urllib.request

import pytest

from gfgmd.core import web


@pytest.fixture(autouse=True)
def no_proxy_after():
    yield
    web.use_proxy("")


def test_an_http_proxy_carries_the_apps_own_requests() -> None:
    web.use_proxy(" http://proxy.example:8080 ")
    assert web.proxy_handler().proxies == {"http": "http://proxy.example:8080", "https": "http://proxy.example:8080"}


def test_a_socks_proxy_or_none_leaves_windows_settings() -> None:
    """The standard library can't speak SOCKS, so those requests follow Windows' proxy settings."""
    system = urllib.request.ProxyHandler().proxies
    web.use_proxy("socks5://proxy.example:1080")
    assert web.proxy_handler().proxies == system
    web.use_proxy("")
    assert web.proxy_handler().proxies == system


def test_only_https_is_opened_or_followed() -> None:
    """A plain-HTTP address is refused before anything is sent, and so is a redirect to one."""
    with pytest.raises(urllib.error.URLError):
        web.open_url("http://example.com/a.jpg", timeout=1)
    request = urllib.request.Request("https://example.com/a.jpg")
    with pytest.raises(urllib.error.URLError):
        web._HttpsOnly().redirect_request(request, None, 302, "Found", {}, "http://example.com/b.jpg")
    followed = web._HttpsOnly().redirect_request(request, None, 302, "Found", {}, "https://example.com/b.jpg")
    assert followed is not None and followed.full_url == "https://example.com/b.jpg"
