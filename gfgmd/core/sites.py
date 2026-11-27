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
    # Its posts can hold pictures as well as videos: after yt-dlp saves a post's videos, gallery-dl
    # saves its pictures.
    photos: bool = False
    # A picture site yt-dlp doesn't read: gallery-dl saves everything from it.
    gallery_only: bool = False
    # False for a site the app reads without a sign-in of its own (Spotify: its songs come from
    # YouTube), which Sign-ins leaves out.
    signs_in: bool = True

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
         tracking=("igsh", "igshid", "img_index"), photos=True),
    Site("facebook", "Facebook", ("facebook.com", "fb.watch", "fb.com"), (".facebook.com",),
         "https://www.facebook.com/login/", 2, ("c_user", "xs"),
         shorts=(r"/reel/\d+", r"/share/r/\w+"),
         posts=(r"/watch/?$", r"/[\w.]+/videos/", r"/videos/\d+", r"/video\.php", r"/share/v/\w+",
                r"/photo/?$", r"/[\w.]+/posts/"),
         post_hosts=("fb.watch",), tracking=("mibextid", "rdid", "sfnsn"), photos=True),
    # t.co is X's link shortener; mapping it here gives its links the X sign-in.
    Site("x", "X (Twitter)", ("x.com", "twitter.com", "t.co"), (".x.com", ".twitter.com"),
         "https://x.com/i/flow/login", 2, ("auth_token",),
         posts=(r"/[\w]+/status/\d+", r"/i/(?:web/)?status/\d+"),
         post_hosts=("t.co",), tracking=("s", "t", "ref_src", "ref_url"), photos=True),
    Site("tiktok", "TikTok", ("tiktok.com",), (".tiktok.com",),
         "https://www.tiktok.com/login", 2, ("sessionid", "sid_tt"),
         shorts=(r"/@[\w.-]+/(?:video|photo)/\d+", r"/v/\d+", r"/t/\w+"),
         profiles=(r"/@[\w.-]+/?$",),
         short_hosts=("vm.tiktok.com", "vt.tiktok.com"),
         tracking=("_r", "_t", "is_from_webapp", "sender_device", "sender_web_id", "share_app_id",
                   "share_link_id", "web_id", "is_copy_url"), photos=True),
    Site("snapchat", "Snapchat", ("snapchat.com",), (".snapchat.com",),
         "https://accounts.snapchat.com/accounts/v2/login", 2, shorts=(r"/spotlight/[\w-]+",),
         tracking=("share_id", "locale")),
    Site("pinterest", "Pinterest", ("pinterest.com", "pin.it"), (".pinterest.com",),
         "https://www.pinterest.com/login/", 2, ("_pinterest_sess",), posts=(r"/pin/\d+",),
         post_hosts=("pin.it",), photos=True),
    Site("vimeo", "Vimeo", ("vimeo.com",), (".vimeo.com",),
         "https://vimeo.com/log_in", auth_cookies=("vimeo",)),
    Site("twitch", "Twitch", ("twitch.tv",), (".twitch.tv",),
         "https://www.twitch.tv/login", auth_cookies=("auth-token",)),
    Site("reddit", "Reddit", ("reddit.com", "redd.it"), (".reddit.com",),
         "https://www.reddit.com/login/", auth_cookies=("reddit_session", "token_v2"),
         posts=(r"/r/\w+/comments/", r"/comments/", r"/r/\w+/s/\w+", r"/gallery/\w+"),
         post_hosts=("v.redd.it", "redd.it", "i.redd.it"), tracking=("share_id", "ref", "ref_source"), photos=True),
    Site("dailymotion", "Dailymotion", ("dailymotion.com", "dai.ly"), (".dailymotion.com",),
         "https://www.dailymotion.com/signin"),
    Site("soundcloud", "SoundCloud", ("soundcloud.com",), (".soundcloud.com",), "https://soundcloud.com/signin"),
    Site("tumblr", "Tumblr", ("tumblr.com",), (".tumblr.com",), "https://www.tumblr.com/login",
         posts=(r"/post/\d+", r"/[\w-]+/\d{6,}"), photos=True),
    Site("bluesky", "Bluesky", ("bsky.app",), (".bsky.app",), "https://bsky.app/",
         posts=(r"/profile/[\w.:-]+/post/\w+",), photos=True),
    # Spotify's playlists, albums, and songs, downloaded from YouTube (see core/spotify.py).
    Site("spotify", "Spotify", ("spotify.com", "spotify.link"), (".spotify.com",), "https://accounts.spotify.com/login",
         tracking=("si", "context", "nd", "pi"), signs_in=False),
    # Picture sites: gallery-dl saves a post's pictures, or a whole profile's when its link is given.
    Site("pixiv", "pixiv", ("pixiv.net",), (".pixiv.net",), "https://accounts.pixiv.net/login", 2, ("PHPSESSID",),
         posts=(r"/(?:\w{2}/)?artworks/\d+",), profiles=(r"/(?:\w{2}/)?users/\d+",), gallery_only=True),
    Site("deviantart", "DeviantArt", ("deviantart.com",), (".deviantart.com",), "https://www.deviantart.com/users/login",
         posts=(r"/[\w-]+/art/",), profiles=(r"/[\w-]+/?$", r"/[\w-]+/gallery"), gallery_only=True),
    Site("imgur", "Imgur", ("imgur.com",), (".imgur.com",), "https://imgur.com/signin",
         posts=(r"/(?:a|gallery|t/\w+)/\w+", r"/\w{5,8}(?:\.\w+)?/?$"), profiles=(r"/user/[\w-]+",),
         post_hosts=("i.imgur.com",), gallery_only=True),
    Site("artstation", "ArtStation", ("artstation.com",), (".artstation.com",), "https://www.artstation.com/users/sign_in",
         posts=(r"/artwork/\w+",), profiles=(r"/[\w-]+/?$",), gallery_only=True),
    Site("flickr", "Flickr", ("flickr.com", "flic.kr"), (".flickr.com",), "https://identity.flickr.com/login",
         posts=(r"/photos/[\w@-]+/\d+", r"/photos/[\w@-]+/(?:albums|sets)/\d+"),
         profiles=(r"/photos/[\w@-]+/?$",), post_hosts=("flic.kr",), gallery_only=True),
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
    "mixcloud.com": "Mixcloud", "audiomack.com": "Audiomack",
    "bitchute.com": "BitChute", "ted.com": "TED", "nebula.tv": "Nebula", "loom.com": "Loom", "9gag.com": "9GAG",
    "threads.net": "Threads", "threads.com": "Threads", "linkedin.com": "LinkedIn", "vk.com": "VK", "ok.ru": "OK",
    "rutube.ru": "RUTUBE", "nicovideo.jp": "Niconico", "bbc.co.uk": "BBC", "cnn.com": "CNN", "nytimes.com": "The New York Times",
    "dropbox.com": "Dropbox", "drive.google.com": "Google Drive", "patreon.com": "Patreon",
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
