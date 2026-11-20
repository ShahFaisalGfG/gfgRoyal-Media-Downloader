"""Site profiles: the hosts, sign-in cookie domains, login pages, and politeness limits of known sites.

Any site yt-dlp supports can be downloaded; a profile only adds what the app knows about a site:
its display name, which cookies belong to it, where to sign in, and how many downloads may run
against it at once. Sites without a profile use the generic one built from the link's host.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    """What the app knows about one site."""

    key: str
    label: str
    hosts: tuple[str, ...]
    # Cookie domains handed to yt-dlp for this site's downloads (leading dot covers subdomains).
    cookie_domains: tuple[str, ...]
    login_url: str
    max_concurrent: int = 3
    # Cookies that prove a signed-in session; an import without any of them signed nobody in.
    auth_cookies: tuple[str, ...] = ()
    # Link paths (regular expressions matched from the start of the path) of one short-form video,
    # of a post that may hold several videos, and of a user's profile.
    shorts: tuple[str, ...] = ()
    posts: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    # Hosts whose every link is a short or a post (share links that redirect to one).
    short_hosts: tuple[str, ...] = ()
    post_hosts: tuple[str, ...] = ()
    # Query parameters that only record who shared the link; dropped so one video has one link.
    tracking: tuple[str, ...] = ()
    # A list only a signed-in account can open; reading its first entry proves a sign-in works.
    check_url: str = ""
    # The account's own lists, offered once signed in: (label, link).
    library: tuple[tuple[str, str], ...] = ()

    def link_kind(self, host: str, path: str) -> str:
        """"short", "post", "profile", or "" for a link on this site."""
        host = host.lower()
        if host in self.short_hosts:
            return "short"
        if host in self.post_hosts:
            return "post"
        for kind, patterns in (("short", self.shorts), ("post", self.posts), ("profile", self.profiles)):
            if any(re.match(pattern, path) for pattern in patterns):
                return kind
        return ""


SITES: tuple[Site, ...] = (
    Site("youtube", "YouTube", ("youtube.com", "youtu.be", "youtube-nocookie.com"),
         (".youtube.com", ".google.com", "accounts.google.com"),
         "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/",
         auth_cookies=("SAPISID", "__Secure-3PSID", "__Secure-1PSID", "LOGIN_INFO", "SID"),
         tracking=("si", "pp"), check_url="https://www.youtube.com/playlist?list=WL",
         library=(("Watch later", "https://www.youtube.com/playlist?list=WL"),
                  ("Liked videos", "https://www.youtube.com/playlist?list=LL"),
                  ("Your playlists", "https://www.youtube.com/feed/playlists"))),
    # Instagram's profile and X's timeline extractors don't work in yt-dlp, so only their posts and
    # reels are classified; other links on them go to yt-dlp as they are.
    Site("instagram", "Instagram", ("instagram.com",), (".instagram.com",),
         "https://www.instagram.com/accounts/login/", 2, ("sessionid",),
         shorts=(r"/(?:[\w.]+/)?(?:reels?|tv)/[\w-]+",),
         posts=(r"/(?:[\w.]+/)?p/[\w-]+", r"/stories/[\w.]+"),
         tracking=("igsh", "igshid", "img_index")),
    Site("facebook", "Facebook", ("facebook.com", "fb.watch", "fb.com"), (".facebook.com",),
         "https://www.facebook.com/login/", 2, ("c_user", "xs"),
         shorts=(r"/reel/\d+", r"/share/r/\w+"),
         posts=(r"/watch/?$", r"/[\w.]+/videos/", r"/videos/\d+", r"/video\.php", r"/share/v/\w+"),
         post_hosts=("fb.watch",), tracking=("mibextid", "rdid", "sfnsn")),
    # t.co is X's link shortener; mapping it here gives its links the X sign-in.
    Site("x", "X (Twitter)", ("x.com", "twitter.com", "t.co"), (".x.com", ".twitter.com"),
         "https://x.com/i/flow/login", 2, ("auth_token",),
         posts=(r"/[\w]+/status/\d+", r"/i/(?:web/)?status/\d+"),
         post_hosts=("t.co",), tracking=("s", "t", "ref_src", "ref_url")),
    Site("tiktok", "TikTok", ("tiktok.com",), (".tiktok.com",),
         "https://www.tiktok.com/login", 2, ("sessionid", "sid_tt"),
         shorts=(r"/@[\w.-]+/(?:video|photo)/\d+", r"/v/\d+", r"/t/\w+"),
         profiles=(r"/@[\w.-]+/?$",),
         short_hosts=("vm.tiktok.com", "vt.tiktok.com"),
         tracking=("_r", "_t", "is_from_webapp", "sender_device", "sender_web_id", "share_app_id",
                   "share_link_id", "web_id", "is_copy_url")),
    Site("snapchat", "Snapchat", ("snapchat.com",), (".snapchat.com",),
         "https://accounts.snapchat.com/accounts/v2/login", 2, shorts=(r"/spotlight/[\w-]+",),
         tracking=("share_id", "locale")),
    Site("pinterest", "Pinterest", ("pinterest.com", "pin.it"), (".pinterest.com",),
         "https://www.pinterest.com/login/", 2, ("_pinterest_sess",), posts=(r"/pin/\d+",),
         post_hosts=("pin.it",)),
    Site("vimeo", "Vimeo", ("vimeo.com",), (".vimeo.com",),
         "https://vimeo.com/log_in", auth_cookies=("vimeo",)),
    Site("twitch", "Twitch", ("twitch.tv",), (".twitch.tv",),
         "https://www.twitch.tv/login", auth_cookies=("auth-token",)),
    Site("reddit", "Reddit", ("reddit.com", "redd.it"), (".reddit.com",),
         "https://www.reddit.com/login/", auth_cookies=("reddit_session", "token_v2"),
         posts=(r"/r/\w+/comments/", r"/comments/", r"/r/\w+/s/\w+"), post_hosts=("v.redd.it", "redd.it"),
         tracking=("share_id", "ref", "ref_source")),
    Site("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly"), (".dailymotion.com",),
         "https://www.dailymotion.com/signin"),
    Site("soundcloud", "SoundCloud", ("soundcloud.com",), (".soundcloud.com",), "https://soundcloud.com/signin"),
)

_BY_KEY = {site.key: site for site in SITES}


def site_for_host(host: str) -> Site | None:
    """The profile whose hosts include `host` or a parent domain of it, if any."""
    host = host.lower().rstrip(".")
    for site in SITES:
        for known in site.hosts:
            if host == known or host.endswith("." + known):
                return site
    return None


def site_by_key(key: str) -> Site | None:
    """The profile with this key, if any."""
    return _BY_KEY.get(key)


# Names of well-known sites the app keeps no profile for, matched on the domain or a parent of it; any
# other site is named by its host.
_NAMES = {
    "bandcamp.com": "Bandcamp", "bilibili.com": "Bilibili", "b23.tv": "Bilibili", "archive.org": "Internet Archive",
    "streamable.com": "Streamable", "odysee.com": "Odysee", "rumble.com": "Rumble", "kick.com": "Kick",
    "mixcloud.com": "Mixcloud", "audiomack.com": "Audiomack", "tumblr.com": "Tumblr", "imgur.com": "Imgur",
    "bitchute.com": "BitChute", "ted.com": "TED", "nebula.tv": "Nebula", "loom.com": "Loom", "9gag.com": "9GAG",
    "threads.net": "Threads", "threads.com": "Threads", "linkedin.com": "LinkedIn", "vk.com": "VK", "ok.ru": "OK",
    "rutube.ru": "RUTUBE", "nicovideo.jp": "Niconico", "bbc.co.uk": "BBC", "cnn.com": "CNN", "nytimes.com": "The New York Times",
    "dropbox.com": "Dropbox", "drive.google.com": "Google Drive", "patreon.com": "Patreon", "spotify.com": "Spotify",
    "deezer.com": "Deezer", "tidal.com": "TIDAL", "apple.com": "Apple", "kakao.com": "Kakao", "naver.com": "NAVER",
    "weibo.com": "Weibo", "douyin.com": "Douyin", "kuaishou.com": "Kuaishou", "likee.video": "Likee",
    "triller.co": "Triller", "trovo.live": "Trovo", "dlive.tv": "DLive", "vidio.com": "Vidio", "iq.com": "iQIYI",
    "youku.com": "Youku", "peertube.tv": "PeerTube", "jiosaavn.com": "JioSaavn", "gaana.com": "Gaana",
}


def site_name(host: str) -> str:
    """A site's name for its host: a well-known one's name, else the host itself."""
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return next((name for domain, name in _NAMES.items() if host == domain or host.endswith("." + domain)), host)


def generic_site(host: str) -> Site:
    """A profile for a site the app has no data for, keyed by its registrable-looking domain."""
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return Site(host, site_name(host), (host,), ("." + host,), f"https://{host}/")


def resolve_site(host: str) -> Site:
    """The known profile for a host, or a generic one."""
    return site_for_host(host) or generic_site(host)
