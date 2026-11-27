"""Spotify playlists, albums, and songs: what they hold, each song found on YouTube, and the saved
songs tagged with Spotify's own details.

Spotify's audio can't be downloaded, so the songs come from YouTube. A link's songs are read from
Spotify's public embed page, in about a second; it lists at most 100 songs. A longer playlist is
read whole by spotDL, one of the download tools, which reads Spotify's web player and can take a
few minutes; without spotDL (or when it fails) the first 100 songs download and the download says
so. spotDL is also the fallback when the embed page can't be read.

Each song is matched by a YouTube search, scored as spotDL scores its matches: the title's words,
the artists, and the length (a song more than MAX_GAP seconds off is never taken), with remixes,
live versions, covers, and the like marked down unless the Spotify title names them. Several songs
share one yt-dlp run, and several runs search at once.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from gfgmd.core import web
from gfgmd.core.analyze import Analysis, Entry
from gfgmd.core.command import base_args, network_args, print_arg, run_marker
from gfgmd.core.errors import CATEGORIES, Failure, classify
from gfgmd.core.jobs import JobExecutor, JobResult, JobSpec
from gfgmd.core.lyrics import Fetch, add_lyrics, fetch_json
from gfgmd.core.naming import unique_target
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import Event, Snapshot, parse_line
from gfgmd.core.runner import Runner, run_to_completion
from gfgmd.core.tags import retag
from gfgmd.core.tools import ToolSet

EMBED_URL = "https://open.spotify.com/embed/{kind}/{id}"
# The embed page lists at most this many songs of a playlist.
EMBED_LIMIT = 100
# YouTube results looked at per song, songs per yt-dlp run, and runs at once.
CANDIDATES = 5
BATCH = 20
RUNS = 4
# A match needs this score (0 to 1), and a length within MAX_GAP seconds of Spotify's.
MIN_SCORE = 0.55
MAX_GAP = 15.0
_PAGE_BYTES = 4_000_000
_COVER_BYTES = 5_000_000
_TIMEOUT = 20.0
# The embed page is served to browsers.
_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
# Spotify's picture hosts: the old one, and the image CDN its pages name now.
_COVER_HOSTS = ("i.scdn.co", ".spotifycdn.com")
# Words that say little about which recording a result is.
_FILLER = {"a", "an", "and", "the", "feat", "ft", "featuring", "featured", "with", "x", "official", "audio",
           "video", "music", "lyrics", "lyric", "visualizer", "hd", "hq", "4k", "explicit", "clean", "version",
           "remastered", "remaster", "prod", "by", "from"}
# Roman numerals read as the digits titles also use ("Men In Black III" and "Men In Black 3"); "i",
# "v", and "x" stay words.
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}
# Words that mark another recording than the album's: marked down unless the Spotify title has them.
_VARIANTS = ("remix", "live", "cover", "karaoke", "slowed", "reverb", "instrumental", "sped", "nightcore", "8d",
             "acoustic", "acapella", "mashup", "boosted", "reaction", "tutorial", "edit")

FetchPage = Callable[[str], str]
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class SpotifySong:
    """One song of a Spotify list, as Spotify names it."""

    id: str
    title: str
    artists: tuple[str, ...]
    duration: float  # seconds, 0 when unknown
    album: str = ""
    track_number: int = 0  # its place on the album; 0 for a playlist's songs
    year: str = ""
    cover: str = ""  # the album's picture, when the list names it

    @property
    def name(self) -> str:
        """"Artist, Other - Title", as the lists and file names show it."""
        return f"{', '.join(self.artists)} - {self.title}" if self.artists else self.title

    @property
    def query(self) -> str:
        """What YouTube is searched for: the main artist and the title."""
        return f"{self.artists[0]} - {self.title}" if self.artists else self.title

    @property
    def url(self) -> str:
        return f"https://open.spotify.com/track/{self.id}"


@dataclass
class SpotifyList:
    """A Spotify link's songs: an album's, a playlist's, or one song."""

    kind: str  # "album", "playlist", or "track"
    id: str
    title: str
    owner: str = ""  # an album's artist, a playlist's maker
    cover: str = ""
    songs: list[SpotifySong] = field(default_factory=list)
    # False for a playlist cut at the embed page's EMBED_LIMIT songs (its first songs only).
    complete: bool = True


@dataclass(frozen=True)
class Candidate:
    """One YouTube result for a song."""

    id: str
    title: str
    channel: str = ""
    duration: float = 0.0

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


class SpotifyError(Exception):
    """The Spotify link couldn't be read; `failure` says why."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.category.message)
        self.failure = failure


# ── Reading the list ──────────────────────────────────────────────────────

def link_parts(url: str) -> tuple[str, str]:
    """("album" | "playlist" | "track", ID) from the link the app keeps for a Spotify source
    ("https://open.spotify.com/album/ID", see sources.py)."""
    parts = urllib.parse.urlsplit(url).path.strip("/").split("/")
    return (parts[-2], parts[-1]) if len(parts) >= 2 else ("", "")


def fetch_page(url: str) -> str:
    """GET Spotify's embed page as text (HTTPS only, through the app's proxy). Raises OSError."""
    request = urllib.request.Request(url, headers={"User-Agent": _BROWSER, "Accept-Language": "en"})
    with web.open_url(request, _TIMEOUT) as response:
        body = response.read(_PAGE_BYTES + 1)
    if len(body) > _PAGE_BYTES:
        raise OSError("Spotify's page is too large")
    return body.decode("utf-8", errors="replace")


def fetch_cover(url: str) -> bytes:
    """GET an album picture from Spotify's picture hosts. Raises OSError for any other host or a bad file."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if not any(host == known or (known.startswith(".") and host.endswith(known)) for known in _COVER_HOSTS):
        raise OSError(f"covers come only from Spotify's picture hosts, not {host}")
    with web.open_url(urllib.request.Request(url, headers={"User-Agent": _BROWSER}), _TIMEOUT) as response:
        body = response.read(_COVER_BYTES + 1)
    if len(body) > _COVER_BYTES or not body.startswith((b"\xff\xd8\xff", b"\x89PNG")):
        raise OSError("the cover isn't a JPEG or PNG picture")
    return body


def _largest_picture(entity: dict[str, Any]) -> str:
    """The largest picture the entity names (its visual identity's, or its cover art's)."""
    pictures = list((entity.get("visualIdentity") or {}).get("image") or [])
    pictures += [{"url": source.get("url"), "maxWidth": source.get("width")}
                 for source in ((entity.get("coverArt") or {}).get("sources") or [])]
    best = max((picture for picture in pictures if isinstance(picture, dict) and picture.get("url")),
               key=lambda picture: picture.get("maxWidth") or 0, default=None)
    return str(best["url"]) if best else ""


def _artists(text: str) -> tuple[str, ...]:
    """The embed page's "Pitbull, Sensato" as ("Pitbull", "Sensato")."""
    return tuple(name.strip() for name in text.replace(" ", " ").split(",") if name.strip())


def _seconds(value: Any) -> float:
    """Milliseconds as seconds (0 when unknown)."""
    return float(value) / 1000.0 if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def parse_embed(html: str) -> SpotifyList:
    """The songs Spotify's embed page lists. Raises ValueError when the page holds no list."""
    found = _NEXT_DATA.search(html)
    if found is None:
        raise ValueError("Spotify's page has no list in it")
    try:
        entity = json.loads(found.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError) as error:
        raise ValueError("Spotify's page changed") from error
    kind = str(entity.get("type") or "")
    if kind not in ("album", "playlist", "track"):
        raise ValueError(f"Spotify's page is for a {kind or 'different kind of'} link")
    title = str(entity.get("name") or entity.get("title") or "")
    cover = _largest_picture(entity)
    year = str((entity.get("releaseDate") or {}).get("isoString") or "")[:4]
    item_id = str(entity.get("id") or "")
    if kind == "track":
        artists = tuple(str(artist.get("name")) for artist in entity.get("artists") or []
                        if isinstance(artist, dict) and artist.get("name"))
        song = SpotifySong(item_id, title, artists, _seconds(entity.get("duration")), year=year, cover=cover)
        return SpotifyList("track", item_id, title, ", ".join(artists), cover, [song])
    rows = [row for row in entity.get("trackList") or [] if isinstance(row, dict) and row.get("entityType", "track") == "track"]
    songs = []
    for number, row in enumerate(rows, start=1):
        song_id = str(row.get("uri") or "").rsplit(":", 1)[-1]
        if not song_id or not row.get("title"):
            continue
        songs.append(SpotifySong(song_id, str(row["title"]), _artists(str(row.get("subtitle") or "")),
                                 _seconds(row.get("duration")), album=title if kind == "album" else "",
                                 track_number=number if kind == "album" else 0, year=year,
                                 cover=cover if kind == "album" else ""))
    complete = not (kind == "playlist" and len(rows) >= EMBED_LIMIT)
    return SpotifyList(kind, item_id, title, str(entity.get("subtitle") or ""), cover, songs, complete)


def parse_spotdl(text: str) -> list[SpotifySong]:
    """The songs in spotDL's save file (a JSON list). Raises ValueError for anything else."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("spotDL's save file holds no list")
    songs = []
    for row in data:
        if not isinstance(row, dict) or not row.get("song_id") or not row.get("name"):
            continue
        number = row.get("track_number")
        songs.append(SpotifySong(
            str(row["song_id"]), str(row["name"]), tuple(str(name) for name in row.get("artists") or [] if name),
            float(row.get("duration") or 0), album=str(row.get("album_name") or ""),
            track_number=number if isinstance(number, int) and row.get("list_url", "").find("/album/") >= 0 else 0,
            year=str(row.get("year") or "")[:4], cover=str(row.get("cover_url") or "")))
    return songs


def spotdl_command(url: str, tools: ToolSet, save_file: Path, options: DownloadOptions) -> list[str]:
    """spotDL's save run: the list's songs into `save_file`, without lyrics or a config file of the user's."""
    command = [tools.spotdl, "save", url, "--save-file", str(save_file), "--headless", "--log-level", "ERROR",
               "--threads", "4"]
    if options.proxy:
        command += ["--proxy", options.proxy]
    return command


def read_with_spotdl(url: str, tools: ToolSet, home: Path, options: DownloadOptions, runner: Runner,
                     stop: threading.Event) -> list[SpotifySong]:
    """Every song of the list, from spotDL (minutes for a long playlist). Raises OSError or ValueError.

    spotDL keeps its settings and cache in the user's home folder; it runs with `home` as that folder,
    so nothing of the user's own spotDL setup is read or changed.
    """
    home.mkdir(parents=True, exist_ok=True)
    save_file = home / "list.spotdl"
    save_file.unlink(missing_ok=True)
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    code, stopped = runner(spotdl_command(url, tools, save_file, options), lambda stream, line: None, stop, env=env)
    if stopped:
        raise OSError("stopped")
    if code != 0 or not save_file.is_file():
        raise OSError(f"spotDL exited with status {code}")
    return parse_spotdl(save_file.read_text(encoding="utf-8"))


def read_list(url: str, tools: ToolSet, home: Path, options: DownloadOptions, page: FetchPage = fetch_page,
              runner: Runner = run_to_completion, stop: threading.Event | None = None) -> SpotifyList:
    """A Spotify link's songs: the embed page's, or spotDL's for a playlist past the page's 100 songs
    (or a page that couldn't be read). Raises SpotifyError."""
    kind, item_id = link_parts(url)
    stop = stop or threading.Event()
    listed: SpotifyList | None = None
    problem: Exception | None = None
    try:
        listed = parse_embed(page(EMBED_URL.format(kind=kind, id=item_id)))
    except (OSError, ValueError) as error:
        problem = error
    if listed is not None and (listed.complete or not tools.spotdl):
        return listed
    if tools.spotdl:
        try:
            songs = read_with_spotdl(url, tools, home, options, runner, stop)
        except (OSError, ValueError) as error:
            songs, problem = [], problem or error
        if songs:
            if listed is not None:
                return replace(listed, songs=songs, complete=True)
            first = songs[0]
            return SpotifyList(kind, item_id, first.album if kind == "album" else first.title,
                               ", ".join(first.artists) if kind != "playlist" else "", first.cover, songs)
    if listed is not None:
        return listed  # the playlist's first 100 songs, which the download says
    if isinstance(problem, OSError) and not isinstance(problem, urllib.error.HTTPError):
        raise SpotifyError(classify(str(problem)))
    raise SpotifyError(Failure(CATEGORIES["spotify_unreadable"], str(problem or "")))


def read_page(url: str, page: FetchPage = fetch_page) -> SpotifyList:
    """The songs Spotify's embed page lists for this link (the first 100 of a longer playlist), for
    Download options: about a second, where spotDL could take minutes. Raises SpotifyError."""
    kind, item_id = link_parts(url)
    try:
        return parse_embed(page(EMBED_URL.format(kind=kind, id=item_id)))
    except urllib.error.HTTPError as error:
        raise SpotifyError(Failure(CATEGORIES["spotify_unreadable"], str(error))) from error
    except OSError as error:
        raise SpotifyError(classify(str(error))) from error
    except ValueError as error:
        raise SpotifyError(Failure(CATEGORIES["spotify_unreadable"], str(error))) from error


def to_analysis(listed: SpotifyList) -> Analysis:
    """The list as Download options shows it: its songs to pick from, or one song."""
    entries = [Entry(song.id, song.name, number, song.duration, song.url, thumbnail=song.cover or listed.cover)
               for number, song in enumerate(listed.songs, start=1)]
    if listed.kind == "track":
        song = listed.songs[0]
        return Analysis("video", song.name, "Spotify", song.url, uploader=", ".join(song.artists),
                        thumbnail=listed.cover, duration=song.duration)
    return Analysis("playlist", listed.title, "Spotify", f"https://open.spotify.com/{listed.kind}/{listed.id}",
                    uploader=listed.owner, thumbnail=listed.cover, entries=entries)


# ── Finding each song on YouTube ──────────────────────────────────────────

def _words(text: str) -> list[str]:
    """The text's words, lowercase and without accents, Roman numerals as digits ("III" as "3")."""
    plain = "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))
    return [_ROMAN.get(word) or word for word in re.findall(r"[^\W_]+", plain)]


def score(song: SpotifySong, candidate: Candidate) -> float:
    """How well a YouTube result fits the song, 0 to 1 (0 for one more than MAX_GAP seconds off)."""
    if song.duration and candidate.duration:
        gap = abs(song.duration - candidate.duration)
        if gap > MAX_GAP:
            return 0.0
        timing = math.exp(-0.1 * gap)
    else:
        timing = 0.5  # one of the lengths is unknown
    named = set(_words(candidate.title)) | set(_words(candidate.channel))
    title_words = set(_words(song.title)) - _FILLER
    titled = len(title_words & named) / len(title_words) if title_words else 0.0
    hits = [all(word in named for word in _words(artist)) for artist in song.artists if _words(artist)]
    credited = sum(hits) / len(hits) if hits else 0.0
    if hits and not hits[0]:
        credited /= 2  # the main artist isn't named: likely another singer's
    # Up to 0.85 for the title, the artists, and the length; the artist's own channel adds 0.05 and
    # YouTube's own "Topic" copy of the released recording 0.1.
    total = 0.85 * (0.4 * titled + 0.25 * credited + 0.35 * timing)
    song_words, result_words = set(_words(song.title)), set(_words(candidate.title))
    total -= 0.15 * sum(1 for word in _VARIANTS if word in result_words and word not in song_words)
    channel = _words(candidate.channel)
    main = _words(song.artists[0]) if song.artists else []
    if main and (all(word in channel for word in main) or "".join(main) in "".join(channel)):
        total += 0.05
    if candidate.channel.endswith(" - Topic"):
        total += 0.1
    return max(0.0, min(1.0, total))


def best_match(song: SpotifySong, candidates: Sequence[Candidate]) -> Candidate | None:
    """The best-scoring result at MIN_SCORE or above, else None."""
    scored = [(score(song, candidate), index, candidate) for index, candidate in enumerate(candidates)]
    good = [entry for entry in scored if entry[0] >= MIN_SCORE]
    return max(good, key=lambda entry: (entry[0], -entry[1]))[2] if good else None


def search_command(songs: Sequence[SpotifySong], tools: ToolSet, cache_dir: Path, options: DownloadOptions,
                   marker: str) -> list[str]:
    """One yt-dlp run searching YouTube for each song; every result names its search."""
    fields = "id,title,channel,uploader,duration,playlist_id,_type"
    command = base_args(tools, cache_dir) + ["--flat-playlist", *print_arg("video", f"{marker}entry %(.{{{fields}}})j")]
    return command + network_args(options) + ["--", *(f"ytsearch{CANDIDATES}:{song.query}" for song in songs)]


def _search(songs: Sequence[SpotifySong], tools: ToolSet, cache_dir: Path, options: DownloadOptions,
            runner: Runner, stop: threading.Event) -> dict[str, list[Candidate]]:
    """The YouTube results of each song's search, by the search's words."""
    marker = run_marker()
    found: dict[str, list[Candidate]] = {}

    def collect(stream: str, line: str) -> None:
        event = parse_line(stream, line, marker)
        data = event.data
        if event.kind == "entry" and data.get("id") and str(data.get("_type") or "url") in ("url", "video"):
            duration = data.get("duration")
            found.setdefault(str(data.get("playlist_id") or ""), []).append(Candidate(
                str(data["id"]), str(data.get("title") or ""), str(data.get("channel") or data.get("uploader") or ""),
                float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else 0.0))

    runner(search_command(songs, tools, cache_dir, options, marker), collect, stop)
    return found


def match_songs(songs: Sequence[SpotifySong], tools: ToolSet, cache_dir: Path, options: DownloadOptions,
                runner: Runner = run_to_completion, stop: threading.Event | None = None,
                on_progress: Callable[[int], None] | None = None) -> dict[str, Candidate]:
    """Each song's YouTube match, by Spotify ID (a song without a good match is left out)."""
    stop = stop or threading.Event()
    batches = [list(songs[start:start + BATCH]) for start in range(0, len(songs), BATCH)]
    matched: dict[str, Candidate] = {}
    done = 0
    lock = threading.Lock()

    def run(batch: list[SpotifySong]) -> None:
        nonlocal done
        if stop.is_set():
            return
        results = _search(batch, tools, cache_dir, options, runner, stop)
        with lock:
            for song in batch:
                match = best_match(song, results.get(song.query, []))
                if match is not None:
                    matched[song.id] = match
            done += len(batch)
            if on_progress is not None:
                on_progress(done)

    with ThreadPoolExecutor(max_workers=RUNS, thread_name_prefix="gfgmd-spotify") as pool:
        list(pool.map(run, batches))
    return matched


# ── Downloading ───────────────────────────────────────────────────────────

def picked(songs: Sequence[SpotifySong], items: str) -> list[SpotifySong]:
    """The songs at the positions Download options picked ("1:5,8", from 1), or all of them for ""."""
    if not items.strip():
        return list(songs)
    wanted: set[int] = set()
    for part in items.split(","):
        first, colon, last = part.strip().partition(":")
        try:
            start = int(first) if first else 1
            end = int(last) if last else (len(songs) if colon else start)
        except ValueError:
            continue
        wanted.update(range(start, end + 1))
    return [song for number, song in enumerate(songs, start=1) if number in wanted]


def song_tags(song: SpotifySong, listed: SpotifyList) -> dict[str, str]:
    """The tags a saved song gets from Spotify (an album's songs also their place on it)."""
    tags = {"title": song.title, "artist": ", ".join(song.artists), "album": song.album, "date": song.year}
    if listed.kind == "album" and song.track_number:
        tags["track"] = f"{song.track_number}/{len(listed.songs)}"
        tags["album_artist"] = listed.owner
    return tags


class SpotifyExecutor:
    """Download a Spotify link's songs from YouTube: read the list, find each song, download them as
    one list (JobExecutor), and tag and name each with Spotify's details. Call run() on a worker
    thread and stop() from any thread; it offers the queue what JobExecutor does."""

    def __init__(self, spec: JobSpec, tools: Callable[[], ToolSet], home: Path,
                 on_file: Callable[[dict[str, Any], Path], None] | None = None,
                 on_event: Callable[[Event], None] | None = None,
                 update_tools: Callable[[], bool] | None = None, runner: Runner = run_to_completion,
                 lyrics_fetch: Fetch | None = None, page: FetchPage = fetch_page, cover: FetchBytes = fetch_cover,
                 **job_options: Any) -> None:
        self._spec = spec
        self._tools = tools
        self._home = home
        self._on_file = on_file
        self._on_event = on_event
        self._update_tools = update_tools
        self._runner = runner
        self._lyrics_fetch = lyrics_fetch
        self._page = page
        self._cover = cover
        self._job_options = job_options
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._inner: JobExecutor | None = None
        self._snap = Snapshot(title="", stage="Reading the Spotify list")
        self._updates: list[tuple[str, Any]] = []
        self._list: SpotifyList | None = None
        self._by_video: dict[str, SpotifySong] = {}
        self._renamed: dict[Path, Path] = {}
        self._covers: dict[str, Path | None] = {}

    def run(self, sleep: Callable[[float], bool] | None = None) -> JobResult:
        """Read, match, and download; sleep is the wait between attempts, as JobExecutor.run takes it."""
        spec, tools = self._spec, self._tools()
        try:
            listed = read_list(spec.url, tools, self._home, spec.options, self._page, self._runner, self._stop)
        except SpotifyError as error:
            return JobResult("failed", attempts=1, failure=error.failure, kind="audio")
        if self._stop.is_set():
            return JobResult("stopped", kind="audio")
        self._list = listed
        songs = picked(listed.songs, spec.options.items)
        with self._lock:
            self._snap = replace(self._snap, title=listed.title, stage=f"Finding the songs on YouTube (0 of {len(songs)})",
                                 item_count=len(songs))
        matched = self._matches(songs, tools)
        if self._stop.is_set():
            return JobResult("stopped", kind="audio")
        found = [song for song in songs if song.id in matched]
        missing = [Failure(CATEGORIES["no_match"], song.name, song.id) for song in songs if song.id not in matched]
        self._by_video = {matched[song.id].id: song for song in found}
        if spec.source.is_collection:
            # Every song by Spotify's name: a found one under its YouTube ID (as the download reports it),
            # one without a match under its Spotify ID, where its "couldn't be found" shows.
            self._push([("list_title", listed.title), ("listed", [
                {"id": matched[song.id].id if song.id in matched else song.id, "title": song.name,
                 "url": matched[song.id].url if song.id in matched else song.url,
                 "thumbnail": song.cover or listed.cover, "index": number, "duration": song.duration}
                for number, song in enumerate(songs, start=1)])])
        if not found:
            result = JobResult("failed" if missing else "done", attempts=1, skipped=missing, kind="audio",
                               failure=missing[0] if missing else None)
            return self._noted(result)
        folder = listed.title if spec.source.is_collection else ""
        inner_spec = replace(spec, urls=tuple(matched[song.id].url for song in found), folder=folder,
                             options=spec.options.with_changes(kind="audio", items=""))
        self._inner = JobExecutor(inner_spec, self._tools, on_file=self._saved, on_event=self._on_event,
                                  update_tools=self._update_tools, runner=self._runner,
                                  lyrics_fetch=self._lyrics_fetch, **self._job_options)
        if self._stop.is_set():
            return JobResult("stopped", kind="audio")
        result = self._inner.run(sleep=sleep)
        result.files = [self._renamed.get(path, path) for path in result.files]
        result.skipped = [*missing, *result.skipped]
        result.kind = "audio"
        return self._noted(result)

    def _noted(self, result: JobResult) -> JobResult:
        """Say when only the playlist's first songs could be read."""
        if self._list is not None and not self._list.complete:
            result.note = f"Spotify's page lists only the first {EMBED_LIMIT} songs of this playlist"
        return result

    def _matches(self, songs: list[SpotifySong], tools: ToolSet) -> dict[str, Candidate]:
        """The YouTube match of each song, kept in the job's folder so a resumed download doesn't search again."""
        saved = self._spec.paths.job_dir / "spotify-matches.json"
        known: dict[str, Candidate] = {}
        try:
            known = {key: Candidate(**value) for key, value in json.loads(saved.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, TypeError):
            known = {}
        wanted = [song for song in songs if song.id not in known]

        def progress(count: int) -> None:
            done = len(songs) - len(wanted) + count
            with self._lock:
                self._snap = replace(self._snap, stage=f"Finding the songs on YouTube ({done} of {len(songs)})",
                                     overall=done / max(1, len(songs)))

        found = match_songs(wanted, tools, self._spec.paths.cache_dir, self._spec.options, self._runner, self._stop,
                            progress) if wanted else {}
        known.update(found)
        try:
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({key: vars(value) for key, value in known.items()}), encoding="utf-8")
        except OSError:
            pass  # searched again next time
        return known

    def _saved(self, info: dict[str, Any], path: Path) -> None:
        """A song was saved: tag it with Spotify's details, name it "Artist - Title", and pass it on."""
        song = self._by_video.get(str(info.get("id") or ""))
        listed = self._list
        if song is not None and listed is not None:
            tools = self._tools()
            retag(path, song_tags(song, listed), tools.ffmpeg, tools.ffprobe, self._cover_file(song.cover))
            path = self._rename(path, song)
            if self._spec.options.lyrics and not path.with_suffix(".lrc").is_file():
                # A second look for lyrics, with Spotify's names rather than the YouTube title's.
                add_lyrics(path, {"track": song.title, "artist": song.artists[0] if song.artists else "",
                                  "album": song.album, "duration": song.duration},
                           "", self._spec.options.lyrics_online, tools.ffmpeg, tools.ffprobe,
                           self._lyrics_fetch or fetch_json)
            info = {**info, "title": song.name, "artist": ", ".join(song.artists), "album": song.album,
                    "thumbnail": song.cover or info.get("thumbnail"), "webpage_url": song.url}
        if self._on_file is not None:
            self._on_file(info, path)

    def _rename(self, path: Path, song: SpotifySong) -> Path:
        """The song named "Artist - Title" (its lyrics file along with it); the old name when that fails."""
        stem = _file_stem(song.name)
        if not stem or path.stem == stem:
            return path
        try:
            occupied = {entry.name.casefold() for entry in path.parent.iterdir()}
            target = unique_target(path.parent, stem, "", path.suffix[1:], occupied)
            os.replace(path, target)
        except OSError:
            return path
        lyrics = path.with_suffix(".lrc")
        if lyrics.is_file():
            try:
                os.replace(lyrics, target.with_suffix(".lrc"))
            except OSError:
                pass
        with self._lock:
            self._renamed[path] = target
        return target

    def _cover_file(self, url: str) -> Path | None:
        """The album picture as a file in the job's folder (fetched once per album), or None."""
        if not url:
            return None
        if url not in self._covers:
            target = self._spec.paths.job_dir / "covers" / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.jpg"
            try:
                if not target.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(self._cover(url))
                self._covers[url] = target
            except OSError:
                self._covers[url] = None  # the song keeps the YouTube picture
        return self._covers[url]

    def _push(self, updates: list[tuple[str, Any]]) -> None:
        with self._lock:
            self._updates.extend(updates)

    def take_updates(self) -> list[tuple[str, Any]]:
        """The list (once the songs are found) and the download's own updates since the last call; the
        songs keep Spotify's names, not the YouTube titles the download would give them."""
        with self._lock:
            updates, self._updates = self._updates, []
        inner = self._inner.take_updates() if self._inner is not None else []
        return updates + [update for update in inner if update[0] != "titled"]

    def stop(self) -> None:
        self._stop.set()
        if self._inner is not None:
            self._inner.stop()

    def snapshot(self) -> Snapshot:
        if self._inner is not None:
            return self._inner.snapshot()
        with self._lock:
            return replace(self._snap)

    def partial_files(self) -> set[str]:
        return self._inner.partial_files() if self._inner is not None else set()

    @property
    def retries(self) -> int:
        return self._inner.retries if self._inner is not None else 0


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _file_stem(name: str) -> str:
    """A file name Windows accepts for "Artist - Title", at most 150 characters."""
    return _UNSAFE.sub("_", name).strip().rstrip(". ")[:150].rstrip(". ")
