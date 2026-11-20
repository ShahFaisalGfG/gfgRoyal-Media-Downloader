"""The app's own web requests (lyrics, thumbnails, tool downloads) through the proxy set in
Preferences > Network, as downloads go through it.

The standard library speaks HTTP proxies only: with a SOCKS proxy chosen (which downloads use),
these requests follow Windows' proxy settings instead. The app's updater keeps Windows' settings too.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

# The proxy chosen in the app ("" when none): set by the app when Preferences change, and by the
# command line from --proxy.
_proxy = ""


def use_proxy(proxy: str) -> None:
    """Send the app's own requests through this proxy ("" for Windows' proxy settings)."""
    global _proxy
    _proxy = proxy.strip()


def proxy_handler() -> urllib.request.ProxyHandler:
    """The chosen HTTP proxy, or Windows' proxy settings when there is none (or it is a SOCKS one)."""
    if urlsplit(_proxy).scheme.lower() in ("http", "https"):
        return urllib.request.ProxyHandler({"http": _proxy, "https": _proxy})
    return urllib.request.ProxyHandler()


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Refuses a redirect to anything but HTTPS before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - urllib's hook
        if urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError(f"redirected away from HTTPS to {urlsplit(newurl).hostname or newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(request: urllib.request.Request | str, timeout: float, https_only: bool = True,
             redirects: urllib.request.HTTPRedirectHandler | None = None) -> Any:
    """Open a request through the app's proxy. With `https_only` (the default) the address and every
    redirect must be HTTPS; `redirects` replaces that check with a stricter one of the caller's."""
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if https_only and urlsplit(url).scheme != "https":
        raise urllib.error.URLError(f"only HTTPS addresses are opened, not {url}")
    handler = redirects or (_HttpsOnly() if https_only else urllib.request.HTTPRedirectHandler())
    return urllib.request.build_opener(proxy_handler(), handler).open(request, timeout=timeout)
