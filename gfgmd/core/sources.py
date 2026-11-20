"""Classify a link: a YouTube playlist, video, Short, or channel; a short, post, or profile on another
known site; or a link to any other site, which yt-dlp reads as it is."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, parse_qs, urlencode, urlparse, urlunparse

from gfgmd.core.sites import Site, resolve_site, site_by_key

# "post" is one post that may hold several videos (an X post, an Instagram carousel); "profile" is a
# user's page on a site other than YouTube (a TikTok @user).
SourceKind = Literal["playlist", "video", "short", "channel", "post", "profile", "generic"]

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
CHANNEL_TABS = {"videos": "Videos", "shorts": "Shorts", "streams": "Live"}
MAX_URL_LENGTH = 4096
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
# Share-tracking parameters on every site.
_TRACKING = ("fbclid", "gclid", "igshid")
_COLLECTIONS = {"playlist", "channel", "post", "profile", "generic"}
# What a YouTube link that is cut short or mistyped gets told (the app and the CLI show it as it is).
_BROKEN_PLAYLIST = "This YouTube playlist link looks broken. Copy the playlist's link again."
_BROKEN_VIDEO = "This YouTube link looks incomplete. Copy the video's link again."


@dataclass(frozen=True)
class Source:
    """What a link points to, and the stable key its download archive is named after."""

    kind: SourceKind
    source_id: str
    site: str = "youtube"
    # The channel tab ("videos", "shorts", "streams") for a channel link, else "".
    tab: str = ""

    @property
    def archive_key(self) -> str:
        """The archive file's name stem, matching the original script for YouTube links."""
        if self.kind == "video":
            return "single-videos"
        if self.kind == "short":
            return "shorts" if self.site == "youtube" else f"{self.site}-shorts"
        if self.kind == "post":
            return f"{self.site}-posts"
        digest = hashlib.sha256(self.source_id.encode("utf-8")).hexdigest()[:16]
        return digest if self.kind == "playlist" else f"{self.kind}-{digest}"

    @property
    def is_collection(self) -> bool:
        """True when the link can hold many videos: a playlist, channel, profile, post, or unknown page."""
        return self.kind in _COLLECTIONS


# Kept for the original script's callers and tests: a YouTube link's classification.
YouTubeSource = Source


# A site's address and path typed without "https://" ("youtu.be/abc", "www.youtube.com/watch?v=...").
_BARE_LINK = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+/\S", re.IGNORECASE)


def as_link(text: str) -> str:
    """The text with "https://" in front when it is a site's address and path typed without it."""
    text = text.strip()
    return f"https://{text}" if _BARE_LINK.match(text) else text


def check_url(url: str) -> str:
    """Return the link without surrounding spaces, or raise ValueError when it can't be a web link."""
    url = url.strip()
    if not url:
        raise ValueError("Paste a link to a video, playlist, or channel.")
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("This link is too long. Copy it again from your browser.")
    if _CONTROL.search(url):
        raise ValueError("The link has spaces or hidden characters in it. Copy it again.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Paste a link that starts with https:// (copy it from your browser's address bar).")
    return url


def source_from_url(url: str) -> Source:
    """Classify a link; YouTube links are checked strictly, other sites are left to yt-dlp."""
    url = check_url(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in YOUTUBE_HOSTS or host in SHORT_HOSTS:
        return _youtube_source(parsed.path, parsed.query, host)
    site = resolve_site(host)
    if site.key == "youtube":  # youtube-nocookie.com and other YouTube domains
        return _youtube_source(parsed.path, parsed.query, "www.youtube.com")
    link = clean_url(url, site)
    kind = site.link_kind(host, parsed.path or "/")
    if kind in ("short", "post", "profile"):
        return Source(kind, link, site.key)  # type: ignore[arg-type]
    return Source("generic", link, site.key)


# Direct links to media files, which yt-dlp downloads as they are.
_MEDIA_FILE = re.compile(r"\.(?:mp4|m4v|mkv|webm|mov|mp3|m4a|aac|opus|ogg|flac|wav|m3u8|mpd)$", re.IGNORECASE)


def likely_media(url: str) -> bool:
    """True for a link worth offering to download: a known media site, or a direct media file.

    The clipboard watcher asks this, so copying an ordinary web link doesn't pop up an offer.
    """
    try:
        source = source_from_url(url)
    except ValueError:
        return False
    return site_by_key(source.site) is not None or bool(_MEDIA_FILE.search(urlparse(url).path))


def clean_url(url: str, site: Site | None = None) -> str:
    """The link without its #fragment and share-tracking parameters, so one video has one link."""
    parsed = urlparse(url.strip())
    site = site or resolve_site((parsed.hostname or "").lower())
    drop = set(_TRACKING) | set(site.tracking)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key not in drop and not key.startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True), fragment=""))


def _youtube_source(path: str, query_text: str, host: str) -> Source:
    query = parse_qs(query_text, keep_blank_values=True)
    if "list" in query:
        playlist_ids = query["list"]
        if len(playlist_ids) != 1 or not playlist_ids[0]:
            raise ValueError(_BROKEN_PLAYLIST)
        return Source("playlist", playlist_ids[0])

    parts = [part for part in path.split("/") if part]
    if host in SHORT_HOSTS:
        if len(parts) != 1:
            raise ValueError(_BROKEN_VIDEO)
        return _video(parts[0], "video")
    if parts == ["watch"]:
        video_ids = query.get("v", [])
        return _video(video_ids[0] if len(video_ids) == 1 else "", "video")
    if len(parts) == 2 and parts[0] in {"shorts", "live", "embed", "v"}:
        return _video(parts[1], "short" if parts[0] == "shorts" else "video")
    if parts == ["playlist"]:
        raise ValueError(_BROKEN_PLAYLIST)
    if parts == ["feed", "playlists"]:
        # A signed-in account's own playlists; each one downloads into its own folder.
        return Source("playlist", "feed-playlists")
    channel = _channel(parts)
    if channel is not None:
        return channel
    raise ValueError("This YouTube link isn't a video, Short, playlist, or channel. Copy the link of one of those.")


def _video(video_id: str, kind: Literal["video", "short"]) -> Source:
    if VIDEO_ID.fullmatch(video_id) is None:
        raise ValueError(_BROKEN_VIDEO)
    return Source(kind, video_id)


def _channel(parts: list[str]) -> Source | None:
    """A channel link (@handle, channel/UC..., c/name, user/name), optionally with a tab."""
    if not parts:
        return None
    if parts[0].startswith("@") and len(parts[0]) > 1:
        name, rest = parts[0], parts[1:]
    elif parts[0] in {"channel", "c", "user"} and len(parts) >= 2:
        name, rest = f"{parts[0]}/{parts[1]}", parts[2:]
    else:
        return None
    if not rest:
        return Source("channel", name)
    if len(rest) == 1 and rest[0] in CHANNEL_TABS:
        return Source("channel", f"{name}/{rest[0]}", tab=rest[0])
    return None


def canonical_url(source: Source, original: str) -> str:
    """The link yt-dlp is given: the original script passed YouTube links as typed, which keeps playlist positions."""
    if source.kind == "channel":
        return f"https://www.youtube.com/{source.source_id}"
    if source.site == "youtube":
        return clean_url(original, resolve_site("youtube.com"))
    return source.source_id
