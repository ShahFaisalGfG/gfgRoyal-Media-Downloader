"""A YouTube link's quick title from oEmbed, through an injected fetcher (no site is contacted)."""

from urllib.parse import parse_qs, urlsplit

from gfgmd.core.quick_info import OEMBED_URL, QuickInfo, quick_info
from gfgmd.core.sources import source_from_url

VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_a_youtube_video_or_playlist_gets_its_title_and_thumbnail() -> None:
    asked: list[str] = []

    def fetch(url: str) -> dict:
        asked.append(url)
        return {"title": " Never Gonna Give You Up ", "author_name": "Rick Astley",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}

    assert quick_info(source_from_url(VIDEO), VIDEO, fetch) == QuickInfo(
        "Never Gonna Give You Up", "Rick Astley", "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    assert asked[0].startswith(OEMBED_URL + "?") and parse_qs(urlsplit(asked[0]).query)["url"] == [VIDEO]
    playlist = "https://www.youtube.com/playlist?list=PLtest123"
    assert quick_info(source_from_url(playlist), playlist, fetch) is not None


def test_other_links_and_failures_wait_for_yt_dlp() -> None:
    def broken(_url: str) -> dict:
        raise OSError("offline")

    def odd(_url: str) -> object:
        return {"title": "", "thumbnail_url": "http://insecure"}

    assert quick_info(source_from_url(VIDEO), VIDEO, broken) is None
    assert quick_info(source_from_url(VIDEO), VIDEO, odd) is None
    channel = "https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ"
    assert quick_info(source_from_url(channel), channel, lambda _url: {"title": "x"}) is None
    vimeo = "https://vimeo.com/76979871"
    assert quick_info(source_from_url(vimeo), vimeo, lambda _url: {"title": "x"}) is None


def test_a_thumbnail_that_is_not_https_is_left_out() -> None:
    info = quick_info(source_from_url(VIDEO), VIDEO, lambda _url: {"title": "Clip", "thumbnail_url": "http://x/y.jpg"})
    assert info is not None and info.thumbnail == ""


def test_a_channels_handle_and_tab_come_from_its_link() -> None:
    """oEmbed doesn't cover channels; nothing is fetched for them."""
    def never(_url: str) -> dict:
        raise AssertionError("a channel's title needs no request")

    tab = "https://www.youtube.com/@YouTube/videos"
    assert quick_info(source_from_url(tab), tab, never) == QuickInfo("@YouTube · Videos", "", "")
    whole = "https://www.youtube.com/@YouTube"
    assert quick_info(source_from_url(whole), whole, never) == QuickInfo("@YouTube", "", "")
