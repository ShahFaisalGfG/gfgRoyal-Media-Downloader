"""Link classification: YouTube kinds are strict, other sites pass through to yt-dlp."""

import pytest

from gfgmd.core.sources import Source, as_link, canonical_url, source_from_url

VIDEO_ID = "jNQXAC9IVRw"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.youtube.com/playlist?list=PLtest123", Source("playlist", "PLtest123")),
        (f"https://www.youtube.com/watch?v={VIDEO_ID}&list=PLtest123", Source("playlist", "PLtest123")),
        (f"https://www.youtube.com/watch?v={VIDEO_ID}", Source("video", VIDEO_ID)),
        (f"https://youtu.be/{VIDEO_ID}", Source("video", VIDEO_ID)),
        (f"https://www.youtube.com/live/{VIDEO_ID}", Source("video", VIDEO_ID)),
        (f"https://www.youtube.com/shorts/{VIDEO_ID}", Source("short", VIDEO_ID)),
        (f"https://music.youtube.com/watch?v={VIDEO_ID}", Source("video", VIDEO_ID)),
        (f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}", Source("video", VIDEO_ID)),
        ("https://www.youtube.com/@SomeChannel", Source("channel", "@SomeChannel")),
        ("https://www.youtube.com/@SomeChannel/shorts", Source("channel", "@SomeChannel/shorts", tab="shorts")),
        ("https://www.youtube.com/channel/UCabc/videos", Source("channel", "channel/UCabc/videos", tab="videos")),
        ("  https://vimeo.com/123#t=5  ", Source("generic", "https://vimeo.com/123", "vimeo")),
        ("https://www.instagram.com/reel/abc/", Source("short", "https://www.instagram.com/reel/abc/", "instagram")),
        ("https://example.com/watch/1", Source("generic", "https://example.com/watch/1", "example.com")),
    ],
)
def test_classifies_links(url: str, expected: Source) -> None:
    """Route playlists, videos, Shorts, channels, and other sites to their own archives."""
    assert source_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=test",
        "https://www.youtube.com/playlist?list=",
        "https://www.youtube.com/playlist",
        "https://www.youtube.com/shorts/invalid",
        "https://www.youtube.com/feed/history",
        "ftp://example.com/video",
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "https://exa mple.com/",
        "",
        "https://example.com/" + "a" * 5000,
    ],
)
def test_rejects_unusable_links(url: str) -> None:
    """Reject links that can't be web pages and YouTube links without a usable ID."""
    with pytest.raises(ValueError):
        source_from_url(url)


@pytest.mark.parametrize(
    ("url", "advice"),
    [
        ("https://www.youtube.com/playlist", "Copy the playlist's link again."),
        ("https://www.youtube.com/playlist?list=", "Copy the playlist's link again."),
        ("https://www.youtube.com/shorts/invalid", "Copy the video's link again."),
        ("https://www.youtube.com/feed/history", "Copy the link of one of those."),
        ("https://exa mple.com/", "Copy it again."),
        ("ftp://example.com/video", "starts with https://"),
    ],
)
def test_rejections_say_what_to_do(url: str, advice: str) -> None:
    """The messages reach toasts as they are: plain advice, never URL parts such as "list=" or "ID"."""
    with pytest.raises(ValueError) as error:
        source_from_url(url)
    message = str(error.value)
    assert advice in message
    assert "list=" not in message and " ID" not in message and "parameter" not in message


@pytest.mark.parametrize(("text", "link"), [
    ("youtu.be/jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw"),
    ("  www.youtube.com/watch?v=jNQXAC9IVRw ", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("https://youtu.be/jNQXAC9IVRw", "https://youtu.be/jNQXAC9IVRw"),
    ("http://example.com/a", "http://example.com/a"),
    ("youtube.com", "youtube.com"),  # an address with no page on it stays as typed (and is refused)
    ("not a link", "not a link"),
])
def test_links_typed_without_https_get_it(text: str, link: str) -> None:
    assert as_link(text) == link


def test_archive_keys_match_version_1() -> None:
    """Keep the original script's archive names so its downloads stay skipped."""
    assert source_from_url(f"https://youtu.be/{VIDEO_ID}").archive_key == "single-videos"
    assert source_from_url(f"https://www.youtube.com/shorts/{VIDEO_ID}").archive_key == "shorts"
    playlist = source_from_url("https://www.youtube.com/playlist?list=PLtest123").archive_key
    assert len(playlist) == 16 and playlist.isalnum()
    assert source_from_url("https://vimeo.com/1").archive_key.startswith("generic-")


def test_channel_links_are_rebuilt_canonically() -> None:
    """Send yt-dlp a clean channel link and keep other links as typed."""
    channel = source_from_url("https://m.youtube.com/@Some/videos?si=x")
    assert canonical_url(channel, "https://m.youtube.com/@Some/videos?si=x") == "https://www.youtube.com/@Some/videos"
    video = source_from_url(f"https://youtu.be/{VIDEO_ID}?t=4")
    assert canonical_url(video, f" https://youtu.be/{VIDEO_ID}?t=4 ") == f"https://youtu.be/{VIDEO_ID}?t=4"


TIKTOK = "https://www.tiktok.com/@some.user/video/7300000000000000001"


@pytest.mark.parametrize(
    ("url", "kind", "site", "link"),
    [
        (TIKTOK + "?is_from_webapp=1&sender_device=pc", "short", "tiktok", TIKTOK),
        ("https://www.tiktok.com/@some.user/photo/7300000000000000002", "short", "tiktok",
         "https://www.tiktok.com/@some.user/photo/7300000000000000002"),
        ("https://vm.tiktok.com/ZMabc123/", "short", "tiktok", "https://vm.tiktok.com/ZMabc123/"),
        ("https://www.tiktok.com/@some.user", "profile", "tiktok", "https://www.tiktok.com/@some.user"),
        ("https://www.instagram.com/reel/Cabc_12-x/?igsh=abc", "short", "instagram",
         "https://www.instagram.com/reel/Cabc_12-x/"),
        ("https://www.instagram.com/someone/reel/Cabc/", "short", "instagram", "https://www.instagram.com/someone/reel/Cabc/"),
        ("https://www.instagram.com/p/Cabc123/?img_index=2", "post", "instagram", "https://www.instagram.com/p/Cabc123/"),
        ("https://www.instagram.com/stories/someone/123/", "post", "instagram",
         "https://www.instagram.com/stories/someone/123/"),
        ("https://www.facebook.com/reel/123456789?mibextid=x", "short", "facebook", "https://www.facebook.com/reel/123456789"),
        ("https://www.facebook.com/share/r/AbC1/", "short", "facebook", "https://www.facebook.com/share/r/AbC1/"),
        ("https://fb.watch/abcDEF/", "post", "facebook", "https://fb.watch/abcDEF/"),
        ("https://www.facebook.com/watch/?v=123", "post", "facebook", "https://www.facebook.com/watch/?v=123"),
        ("https://x.com/some_user/status/123456?s=20&t=abc", "post", "x", "https://x.com/some_user/status/123456"),
        ("https://twitter.com/i/web/status/123456", "post", "x", "https://twitter.com/i/web/status/123456"),
        ("https://t.co/AbCd", "post", "x", "https://t.co/AbCd"),
        ("https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEni", "short", "snapchat",
         "https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEni"),
        ("https://pin.it/abc", "post", "pinterest", "https://pin.it/abc"),
        ("https://www.reddit.com/r/videos/comments/abc/title/?share_id=1", "post", "reddit",
         "https://www.reddit.com/r/videos/comments/abc/title/"),
        ("https://v.redd.it/abc123", "post", "reddit", "https://v.redd.it/abc123"),
        ("https://vimeo.com/123?utm_source=share&fbclid=1", "generic", "vimeo", "https://vimeo.com/123"),
        ("https://example.com/clip.mp4", "generic", "example.com", "https://example.com/clip.mp4"),
    ],
)
def test_classifies_short_form_and_posts(url: str, kind: str, site: str, link: str) -> None:
    """Shorts, posts, and profiles on known sites; share-tracking parameters dropped from the link."""
    source = source_from_url(url)
    assert (source.kind, source.site, source.source_id) == (kind, site, link)
    assert canonical_url(source, url) == link


def test_short_form_archives_and_collections() -> None:
    """Each site keeps one archive of its shorts and one of its posts; a post may hold several videos."""
    tiktok = source_from_url(TIKTOK)
    post = source_from_url("https://x.com/a/status/1")
    assert tiktok.archive_key == "tiktok-shorts" and not tiktok.is_collection
    assert post.archive_key == "x-posts" and post.is_collection
    assert source_from_url(f"https://www.youtube.com/shorts/{VIDEO_ID}").archive_key == "shorts"


def test_youtube_links_lose_only_share_tracking() -> None:
    """A YouTube share link keeps its start time but drops "si"."""
    url = f"https://youtu.be/{VIDEO_ID}?si=abc&t=30"
    assert canonical_url(source_from_url(url), url) == f"https://youtu.be/{VIDEO_ID}?t=30"


def test_well_known_sites_without_a_profile_have_their_names() -> None:
    from gfgmd.core.sites import resolve_site
    assert resolve_site("youtube-dl.bandcamp.com").label == "Bandcamp"
    assert resolve_site("www.bilibili.com").label == "Bilibili" and resolve_site("archive.org").label == "Internet Archive"
    assert resolve_site("example.org").label == "example.org"
