"""A YouTube link's title, channel, and thumbnail in about a second, from YouTube's oEmbed page.

Download options show them while yt-dlp reads the qualities, subtitles, and entries, which takes
several seconds. Other sites, and a link oEmbed doesn't answer for, wait for yt-dlp as before.
"""

from __future__ import annotations

import http.client
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from gfgmd.core import web
from gfgmd.core.sources import CHANNEL_TABS, Source

OEMBED_URL = "https://www.youtube.com/oembed"
_TIMEOUT = 5.0
_MAX_BYTES = 64 * 1024
# A plain browser name: YouTube refuses some requests from Python's own.
_USER_AGENT = "Mozilla/5.0"

Fetch = Callable[[str], Any]


@dataclass(frozen=True)
class QuickInfo:
    """What a link is, before its details are read."""

    title: str
    uploader: str
    thumbnail: str


def fetch_json(url: str) -> Any:
    """GET a small JSON document over HTTPS through the app's proxy. Raises OSError or ValueError."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with web.open_url(request, _TIMEOUT) as response:
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError("The oEmbed answer is too large")
    return json.loads(body.decode("utf-8"))


def quick_info(source: Source, url: str, fetch: Fetch = fetch_json) -> QuickInfo | None:
    """The title, channel, and thumbnail of a YouTube video or playlist link; None for other links,
    or when YouTube doesn't answer (yt-dlp's read fills them in then). A channel's @handle and tab
    come from the link itself ("@name · Videos"), as oEmbed doesn't cover channels."""
    if source.site == "youtube" and source.kind == "channel":
        return _channel_title(source)
    if source.site != "youtube" or source.kind not in ("video", "short", "playlist"):
        return None
    try:
        data = fetch(f"{OEMBED_URL}?{urllib.parse.urlencode({'url': url, 'format': 'json'})}")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not data["title"].strip():
        return None
    thumbnail = data.get("thumbnail_url")
    return QuickInfo(
        title=data["title"].strip(),
        uploader=str(data.get("author_name") or "").strip(),
        thumbnail=thumbnail if isinstance(thumbnail, str) and thumbnail.startswith("https://") else "",
    )


def _channel_title(source: Source) -> QuickInfo | None:
    """"@name · Videos" from a channel link; None for a channel named only by its ID."""
    handle = source.source_id.split("/")[0]
    if not handle.startswith("@"):
        return None
    tab = CHANNEL_TABS.get(source.tab, "")
    return QuickInfo(title=f"{handle} · {tab}" if tab else handle, uploader="", thumbnail="")
