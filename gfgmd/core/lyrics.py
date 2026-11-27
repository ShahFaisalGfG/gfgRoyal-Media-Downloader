"""Lyrics for audio downloads: a timed "<song>.lrc" beside each file, and plain lyrics in its tags.

The site's own captions come first: they were timed against this very audio. Without them, LRCLIB
(lrclib.net, a free and open lyrics database) is asked by artist, title, and album, and its timed
lyrics are used only when the track length matches the file within LENGTH_TOLERANCE seconds, so
every line lands where it's sung. Nothing here raises: a song without lyrics is still a finished
download. Stdlib only, so the command-line tool shares it.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from gfgmd.config.defaults import AppInfo, UpdateInfo
from gfgmd.core import web
from gfgmd.core.captions import is_synced_lrc, parse_lrc, plain_text, to_lrc
from gfgmd.core.platform import hidden_window_flags
from gfgmd.core.tags import stream_count

LRCLIB_URL = "https://lrclib.net"
# LRCLIB asks clients to name themselves; no personal details are sent.
USER_AGENT = f"{AppInfo.APP_NAME} {AppInfo.APP_VERSION} ({UpdateInfo.REPO_URL})"
LENGTH_TOLERANCE = 2.0
MAX_RESPONSE_BYTES = 1024 * 1024
# Command lines on Windows hold about 32,000 characters; longer lyrics stay in the .lrc file only.
MAX_TAG_CHARS = 16000
# The MP3 tag writer rewrites the whole file in memory; longer files keep their lyrics in the .lrc only.
MAX_TAGGED_BYTES = 256 * 1024 * 1024
_TIMEOUT = 10
# Formats whose tags take plain lyrics: MP3 through an ID3 USLT frame written here, M4A and FLAC
# through an ffmpeg copy. Opus and OGG keep their covers in a tag ffmpeg can't copy back, and WAV
# has no lyrics tag, so those keep the .lrc file only.
_FFMPEG_TAGGED = {".m4a", ".flac"}
_NOISE = re.compile(
    r"\s*[(\[][^)\]]*\b(?:official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|mv|m/v|remaster(?:ed)?|release|"
    r"copyright)\b[^)\]]*[)\]]",
    re.IGNORECASE)
# " | Progressive House | NCS - Copyright Free Music": labels uploaders append after the song.
_SEGMENTS = re.compile(r"\s+[|\uff5c]\s+.*$")
# "(feat. Someone)": lyrics databases often list the song without it.
_FEATURING = re.compile(r"\s*[(\[]?\b(?:feat|ft|featuring)\.?\s[^)\]]*[)\]]?", re.IGNORECASE)
_ARTIST_NOISE = re.compile(r"(?:\s*-\s*Topic|VEVO|\s+Official)$", re.IGNORECASE)

Fetch = Callable[[str], Any]


@dataclass(frozen=True)
class Song:
    """What LRCLIB is asked about one audio file."""

    title: str
    artist: str
    album: str = ""
    length: float = 0.0


@dataclass(frozen=True)
class LyricsResult:
    """What the lyrics step did for one file."""

    source: str = ""  # "site", "lrclib", or "" when none were found
    synced: bool = False
    path: Path | None = None
    embedded: bool = False


def song_from_info(info: dict[str, Any], length: float = 0.0) -> Song:
    """The artist and title of a finished file, cleaned of " - Topic", "(Official Video)", and the like."""
    title = str(info.get("track") or info.get("title") or "").strip()
    artist = str(info.get("artist") or info.get("creator") or "").strip()
    named = bool(artist)  # the site named the artist, rather than only the uploading channel
    if not artist:
        artist = _ARTIST_NOISE.sub("", str(info.get("uploader") or info.get("channel") or "")).strip()
    title = _NOISE.sub("", _SEGMENTS.sub("", title)).strip()
    if " - " in title and not info.get("track"):
        # "Artist - Song" titles, common on uploads that aren't YouTube Music tracks: the title names
        # the artist better than a channel does, unless the site named the artist itself.
        head, tail = (part.strip() for part in title.split(" - ", 1))
        if not named or head.casefold() == artist.casefold():
            artist, title = head, tail
    duration = info.get("duration")
    fallback = float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else 0.0
    return Song(title, artist, str(info.get("album") or "").strip(), length or fallback)


def pick_site_lyrics(audio: Path, languages: str) -> Path | None:
    """The site's caption file for this song ("<song>.<lang>.lrc"), in the order of `languages`."""
    try:
        found = [entry for entry in audio.parent.iterdir()
                 if entry.is_file() and entry.suffix.lower() == ".lrc" and entry.stem.startswith(audio.stem + ".")]
    except OSError:
        return None
    if not found:
        return None
    by_lang = {entry.stem[len(audio.stem) + 1:]: entry for entry in found}
    for pattern in (part.strip() for part in languages.split(",") if part.strip() and not part.startswith("-")):
        for lang in sorted(by_lang):
            try:
                if re.fullmatch(pattern, lang):
                    return by_lang[lang]
            except re.error:
                break
    return found[0]


def fetch_json(url: str) -> Any:
    """GET a JSON document; None for 404. Raises OSError (network) or ValueError (bad data)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        # Through the app's proxy; the address is LRCLIB's own fixed HTTPS one (tests serve it locally).
        with web.open_url(request, _TIMEOUT, https_only=False) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("The lyrics response is too large")
    return json.loads(body.decode("utf-8"))


def lookup_lrclib(song: Song, fetch: Fetch = fetch_json, base_url: str = LRCLIB_URL) -> tuple[str, str]:
    """(timed LRC, plain text) for the song from LRCLIB; ("", "") when it has none that fits.

    A result counts only when its length is within LENGTH_TOLERANCE of the file's, or, when the
    file's length is unknown, when artist and title match exactly.
    """
    if not song.title or not song.artist:
        return "", ""
    candidates: list[dict[str, Any]] = []
    if song.album and song.length:
        exact = fetch(f"{base_url}/api/get?" + urllib.parse.urlencode({
            "track_name": song.title, "artist_name": song.artist, "album_name": song.album,
            "duration": round(song.length)}))
        if isinstance(exact, dict):
            candidates.append(exact)
    # The title without "(feat. ...)" first (how databases usually list a song), then as it is.
    for title in dict.fromkeys((_FEATURING.sub("", song.title).strip() or song.title, song.title)):
        if any(_fits(entry, song) and entry.get("syncedLyrics") for entry in candidates):
            break
        found = fetch(f"{base_url}/api/search?" + urllib.parse.urlencode(
            {"track_name": title, "artist_name": song.artist}))
        if isinstance(found, list):
            candidates += [entry for entry in found if isinstance(entry, dict)]
    fitting = [entry for entry in candidates if _fits(entry, song) and not entry.get("instrumental")]
    synced = next((entry for entry in fitting if isinstance(entry.get("syncedLyrics"), str)
                   and is_synced_lrc(entry["syncedLyrics"])), None)
    plain = next((entry for entry in fitting if isinstance(entry.get("plainLyrics"), str)
                  and entry["plainLyrics"].strip()), None)
    return (str(synced["syncedLyrics"]) if synced else "",
            str((synced or plain or {}).get("plainLyrics") or "").strip())


def _fits(entry: dict[str, Any], song: Song) -> bool:
    length = entry.get("duration")
    if song.length and isinstance(length, (int, float)):
        return abs(float(length) - song.length) <= LENGTH_TOLERANCE
    return (str(entry.get("trackName", "")).casefold() == song.title.casefold()
            and str(entry.get("artistName", "")).casefold() == song.artist.casefold())


def add_uslt(path: Path, text: str, language: str = "XXX") -> bool:
    """Put plain lyrics in an MP3's ID3v2.3 or v2.4 tag as its USLT frame (replacing an old one).

    Returns False, leaving the file alone, for tags this writer doesn't handle (unsynchronised,
    extended headers, footers) or when the file can't be rewritten.
    """
    try:
        if path.stat().st_size > MAX_TAGGED_BYTES:
            return False  # a long mix: the .lrc file carries its lyrics
        data = path.read_bytes()
    except OSError:
        return False
    major = data[3] if data[:3] == b"ID3" and len(data) >= 10 else 4
    if data[:3] == b"ID3":
        if major not in (3, 4) or data[5] & 0xD0:
            return False
        tag_end = 10 + _syncsafe(data[6:10])
        frames, position = [], 10
        while position + 10 <= tag_end and data[position:position + 4] != b"\x00\x00\x00\x00":
            raw = data[position + 4:position + 8]
            size = _syncsafe(raw) if major == 4 else int.from_bytes(raw, "big")
            frame = data[position:position + 10 + size]
            if len(frame) < 10 + size:
                return False  # a damaged tag
            if frame[:4] != b"USLT":
                frames.append(frame)
            position += 10 + size
        audio = data[tag_end:]
    else:
        frames, audio = [], data
    if major == 4:
        body = b"\x03" + language.encode("ascii")[:3] + b"\x00" + text.encode("utf-8")
        size_bytes = _to_syncsafe(len(body))
    else:
        body = (b"\x01" + language.encode("ascii")[:3] + b"\xff\xfe\x00\x00"
                + b"\xff\xfe" + text.encode("utf-16-le"))
        size_bytes = len(body).to_bytes(4, "big")
    frames.append(b"USLT" + size_bytes + b"\x00\x00" + body)
    padding = b"\x00" * 1024
    content = b"".join(frames) + padding
    header = b"ID3" + bytes([major, 0, 0]) + _to_syncsafe(len(content))
    return _replace(path, header + content + audio)


def _syncsafe(raw: bytes) -> int:
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _to_syncsafe(value: int) -> bytes:
    return bytes([(value >> 21) & 0x7F, (value >> 14) & 0x7F, (value >> 7) & 0x7F, value & 0x7F])


def _replace(path: Path, content: bytes) -> bool:
    temporary = path.with_name(path.name + ".lyrics-tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
        return True
    except OSError:
        temporary.unlink(missing_ok=True)
        return False


def tag_with_ffmpeg(path: Path, text: str, ffmpeg: str, ffprobe: str) -> bool:
    """Copy an M4A or FLAC file with a lyrics tag added; kept only when every stream came through."""
    temporary = path.with_name(f"{path.stem}.lyrics-tmp{path.suffix}")
    try:
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", str(path), "-map", "0", "-c", "copy", "-map_metadata", "0",
             "-metadata", f"lyrics={text}", str(temporary)],
            capture_output=True, check=False, timeout=300, creationflags=hidden_window_flags())
        if result.returncode != 0 or stream_count(ffprobe, temporary) != stream_count(ffprobe, path):
            return False
        os.replace(temporary, path)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        temporary.unlink(missing_ok=True)


def file_length(ffprobe: str, path: Path) -> float:
    """The audio's length in seconds as ffprobe reads it (0 when it can't)."""
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(path)], capture_output=True, text=True, check=False, timeout=60,
                                creationflags=hidden_window_flags())
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def add_lyrics(audio: Path, info: dict[str, Any], languages: str, online: bool, ffmpeg: str, ffprobe: str,
               fetch: Fetch = fetch_json, base_url: str = LRCLIB_URL) -> LyricsResult:
    """Save "<song>.lrc" beside `audio` and embed plain lyrics where its format allows; never raises."""
    song = song_from_info(info, file_length(ffprobe, audio))
    lrc_path = audio.with_suffix(".lrc")
    source, synced_text, plain = "", "", ""
    site_file = pick_site_lyrics(audio, languages)
    if site_file is not None:
        try:
            cues = parse_lrc(site_file.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            cues = []
        if cues:
            source = "site"
            synced_text = to_lrc(cues, song.title, song.artist, song.album, song.length)
            plain = plain_text(cues)
    if not source and online:
        try:
            # Untimed lyrics from LRCLIB (no synced version fits) still go in the tag.
            synced_text, plain = lookup_lrclib(song, fetch, base_url)
        except (OSError, ValueError, http.client.HTTPException):
            synced_text, plain = "", ""  # offline or LRCLIB unreachable: the download still counts
        source = "lrclib" if synced_text or plain else ""
    _remove_language_files(audio)
    path = None
    if synced_text:
        try:
            lrc_path.write_text(synced_text if synced_text.endswith("\n") else synced_text + "\n", encoding="utf-8")
            path = lrc_path
        except OSError:
            path = None
        if not plain:
            plain = plain_text(parse_lrc(synced_text))
    embedded = False
    if plain and len(plain) <= MAX_TAG_CHARS:
        if audio.suffix.lower() == ".mp3":
            embedded = add_uslt(audio, plain)
        elif audio.suffix.lower() in _FFMPEG_TAGGED:
            embedded = tag_with_ffmpeg(audio, plain, ffmpeg, ffprobe)
    return LyricsResult(source, bool(path), path, embedded)


def _remove_language_files(audio: Path) -> None:
    """Delete the per-language caption files yt-dlp saved; the chosen one became "<song>.lrc"."""
    try:
        for entry in audio.parent.iterdir():
            if entry.suffix.lower() == ".lrc" and entry.stem.startswith(audio.stem + "."):
                entry.unlink(missing_ok=True)
    except OSError:
        pass  # leftovers do no harm; the player prefers "<song>.lrc"
