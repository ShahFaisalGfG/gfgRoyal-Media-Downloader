"""Build yt-dlp command lines. Pure functions: no I/O, so every flag is covered by unit tests.

Every command:
- loads no yt-dlp configuration, plugin, or remote component, so nothing outside the app can add
  options such as --exec (the original script used --no-config-locations, which still loaded config.txt);
- names ffmpeg and Deno by absolute path, so PATH never decides which program runs;
- passes links after "--", so a link that begins with "-" can never be read as an option.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from gfgmd.core.options import DownloadOptions
from gfgmd.core.platform import hide_folder
from gfgmd.core.sources import CHANNEL_TABS, Source
from gfgmd.core.tools import ToolSet

# The start of the lines the app asks yt-dlp to print. Each run uses its own random one (run_marker),
# so a site's title that yt-dlp prints in its messages can't pass for one of them.
MARKER = "@@gfgr:"
# The archive file of a Download again, in the job's folder (see RunPaths.session_archive).
SESSION_ARCHIVE = "session-archive.txt"
# More links than this go through a batch file, which keeps the command line short.
MAX_INLINE_URLS = 50
# --match-filters entries beyond this are dropped; the skipped items then fail fast and are skipped again.
MAX_SKIP_FILTERS = 200

_ITEM_FIELDS = ("id,extractor_key,title,uploader,channel,duration,live_status,playlist_title,"
                "playlist_index,n_entries,format_id,webpage_url,thumbnail,release_timestamp")
_FILE_FIELDS = ("id,extractor_key,title,filepath,height,width,vcodec,acodec,webpage_url,duration,uploader,"
                "channel,playlist_title,playlist_index,thumbnail,artist,creator,track,album")
_ENTRY_FIELDS = ("id,url,title,duration,live_status,availability,release_timestamp,timestamp,"
                 "playlist_index,ie_key,channel,uploader")
_DOWNLOAD_PROGRESS = (
    'dl {"p":%(progress.{status,downloaded_bytes,total_bytes,total_bytes_estimate,'
    'speed,eta,fragment_index,fragment_count,tmpfilename,filename,elapsed})j,'
    '"i":%(info.{id,format_id,vcodec,acodec,playlist_index,is_live})j}'
)
_POSTPROCESS_PROGRESS = 'pp {"p":%(progress.{status,postprocessor})j,"i":%(info.{id,filepath})j}'
# Characters a Windows folder name can't hold, and control characters.
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_STAGES = {"video", "after_move", "playlist", "before_dl", "pre_process", "after_filter", "post_process"}
# Each order ranks "lang" before any audio field, so the audio track in the video's original language
# wins over dubbed ones. yt-dlp always ranks its own "ie_pref" first, which keeps watermarked TikTok
# formats last.
SORT_PROFILES = {
    "balanced": "lang,res,proto:m3u8,vcodec:h264,acodec:aac",
    "compatible": "vcodec:h264,lang,quality,res,fps,hdr:12,acodec:aac",
    "best": "lang,res,fps,hdr:12",
}
# Audio-only downloads: the original language, then the highest bitrate and sample rate.
AUDIO_SORT = "lang,abr,asr"
# The best audio that isn't YouTube's "stable volume" copy (format IDs ending "-drc"), whose squeezed
# loudness range spoils music; the plain "ba" after it still takes one when nothing else is offered.
FULL_AUDIO = "ba[format_id!*=drc]"
_AUDIO_SELECTORS = {
    "mp3": f"ba[acodec^=mp3]/{FULL_AUDIO}/ba/b",
    "m4a": f"ba[ext=m4a][format_id!*=drc]/ba[ext=m4a]/ba[acodec^=mp4a]/{FULL_AUDIO}/ba/b",
    "opus": f"ba[acodec^=opus][format_id!*=drc]/ba[acodec^=opus]/{FULL_AUDIO}/ba/b",
    "vorbis": f"ba[acodec^=vorbis]/{FULL_AUDIO}/ba/b",
    "flac": f"{FULL_AUDIO}/ba/b",
    "wav": f"{FULL_AUDIO}/ba/b",
    "best": f"{FULL_AUDIO}/ba/b",
}
# A centre crop to a square, for covers. The single quotes keep ffmpeg from reading the commas
# inside the expressions as filter separators.
SQUARE_CROP = "crop='if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'"
# yt-dlp splits these arguments like a shell, so the single quotes reach ffmpeg.
SQUARE_COVER = f'ThumbnailsConvertor+ffmpeg_o:-c:v mjpeg -qmin 1 -qscale:v 1 -vf "{SQUARE_CROP}"'
# What a music video's title says about the video, not the song: "(Official Video)", "[Lyrics]",
# "(HD)", "(4K Remaster)". Songs leave it out of their title tag and file name; "(Live)" and
# "(Remix)" stay, as they name the song.
MUSIC_TITLE_NOISE = r"(?i)\s*[(\[](?:official\s+(?:music\s+|lyrics?\s+)?(?:video|audio|visuali[sz]er|m/?v)(?:\s+hd)?|(?:lyrics?|music)\s+video|with\s+lyrics|lyrics|audio|visuali[sz]er|m/?v|hd|hq|[48]k|(?:[48]k\s+|hd\s+)?remaster(?:ed)?(?:\s+\d{4})?)[)\]]"
# Channel names that aren't the artist: YouTube Music's "<Artist> - Topic" and "<Artist>VEVO".
ARTIST_SUFFIX = r"( - Topic|VEVO)$"
# Facebook titles reels "9.9K views · 340 reactions | <caption>"; the counts don't belong in a file name.
_FACEBOOK_COUNTS = r"^[\d.,]+[KMB]? (?:views|plays)(?: · [\d.,]+[KMB]? reactions)? \| "
# When the site names no artist, an "Artist - Song | labels" title gives the tags their artist and
# title (meta_ fields change only the tags, not the file name). "%(artist|)s" is empty then, so the
# text starts with "@@" and the pattern can match only in that case.
ARTIST_TITLE = r"(?P<meta_artist>[^|]+?) - (?P<meta_title>[^|]+?)(?:\s+\|.*)?$"
_TITLE_TAGS = "%(artist|)s@@%(title)s:^@@" + ARTIST_TITLE
_FILENAME_PREFIX = {
    "title-quality": "",
    "title": "",
    "date-title": "%(upload_date>%Y-%m-%d&{} - |)s",
    "index-title": "%(playlist_index&{:03d} - |)s",
}


@dataclass(frozen=True)
class RunPaths:
    """Where one download writes: its root folder, archive, scratch folder, and yt-dlp cache."""

    root: Path
    archive: Path
    job_dir: Path
    cache_dir: Path

    @property
    def journal(self) -> Path:
        """yt-dlp's own record of each finished file, written as it moves the file into place."""
        return self.job_dir / "files.jsonl"

    @property
    def incomplete(self) -> Path:
        """Where partial files live until yt-dlp moves them into the download folder."""
        return self.root / ".incomplete"

    def prepare(self) -> None:
        """Create the folders a download writes to, hiding the archive and unfinished-file folders."""
        self.job_dir.mkdir(parents=True, exist_ok=True)
        for folder in (self.archive.parent, self.incomplete):
            folder.mkdir(parents=True, exist_ok=True)
            hide_folder(folder)

    @property
    def convert_progress(self) -> Path:
        """Where ffmpeg writes how far an audio conversion has got (yt-dlp reports only its start and end)."""
        return self.job_dir / "convert.progress"

    @property
    def session_archive(self) -> Path:
        """The videos a Download again saved so far, so a pause, a restart, or a retry doesn't fetch
        them a second time; the queue clears it when Download again starts over."""
        return self.job_dir / SESSION_ARCHIVE

    @property
    def lists(self) -> Path:
        """Where yt-dlp writes each playlist's details, with its videos, before downloading them."""
        return self.job_dir / "lists"


@dataclass(frozen=True)
class Auth:
    """How a run signs in: a cookies file, or cookies read from a browser on each run."""

    cookies_file: str = ""
    browser: str = ""  # yt-dlp's --cookies-from-browser value, such as "firefox" or "firefox:Profile"


def escape_template(text: str) -> str:
    """A literal for a yt-dlp output template ("%" is its field marker)."""
    return text.replace("%", "%%")


def folder_name(text: str) -> str:
    """A name Windows accepts for one folder: no path separators or reserved characters, at most 100 long."""
    cleaned = _UNSAFE_NAME.sub("_", text).strip().rstrip(". ")
    return cleaned[:100].rstrip(". ") or "Downloads"


def print_arg(stage: str, template: str) -> list[str]:
    """A --print argument for an allowed stage (yt-dlp silently prints a mistyped stage as text)."""
    if stage not in _STAGES:
        raise ValueError(f"Unknown --print stage: {stage}")
    return ["--print", f"{stage}:{template}"]


def base_args(tools: ToolSet, cache_dir: Path) -> list[str]:
    """The options every yt-dlp run starts with."""
    return [
        tools.ytdlp,
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--no-js-runtimes",
        "--js-runtimes", f"deno:{tools.deno}",
        "--ffmpeg-location", tools.ffmpeg_dir,
        "--cache-dir", str(cache_dir),
        "--color", "never",
        "--encoding", "utf-8",
        "--windows-filenames",
        "--socket-timeout", "30",
        "--no-quiet",
        "--newline",
    ]


def retry_args() -> list[str]:
    """yt-dlp's own retries inside one attempt (the original script's values)."""
    return [
        "--retries", "10",
        "--fragment-retries", "10",
        "--extractor-retries", "5",
        "--file-access-retries", "5",
        "--retry-sleep", "http:exp=1:30",
        "--retry-sleep", "fragment:exp=1:30",
        "--retry-sleep", "extractor:exp=1:30",
        "--retry-sleep", "file_access:exp=1:30",
    ]


def auth_args(auth: Auth | None) -> list[str]:
    """--cookies or --cookies-from-browser, when the run signs in."""
    if auth is None:
        return []
    if auth.cookies_file:
        return ["--cookies", auth.cookies_file]
    if auth.browser:
        return ["--cookies-from-browser", auth.browser]
    return []


def network_args(options: DownloadOptions) -> list[str]:
    """Proxy, IPv4, and speed limit options."""
    args: list[str] = []
    if options.proxy:
        args += ["--proxy", options.proxy]
    if options.force_ipv4:
        args.append("--force-ipv4")
    if options.limit_rate > 0:
        args += ["--limit-rate", str(options.limit_rate)]
    return args


def url_args(urls: Sequence[str], job_dir: Path) -> tuple[list[str], str]:
    """The links after "--", or a batch file for many links; returns (args, batch file text or "")."""
    if len(urls) > MAX_INLINE_URLS:
        batch = job_dir / "urls.txt"
        return ["--batch-file", str(batch)], "".join(f"{url}\n" for url in urls)
    return ["--", *urls], ""


def format_selector(options: DownloadOptions) -> str:
    """The -f selector: the best format whose shorter side fits the limit (the original script's rule).

    Portrait formats (aspect ratio below 1) are capped by width and landscape ones by height, so
    one limit fits Shorts and regular videos alike. The last pair accepts formats a site reports
    without a height. Audio selectors prefer a stream that needs no conversion.
    """
    if options.kind == "audio":
        return _AUDIO_SELECTORS[options.audio_format]
    height = options.max_height
    if not height:
        return _with_audio("bv*", "b", options)
    portrait = _with_audio(f"bv[width<={height}][aspect_ratio<1]", f"b[width<={height}][aspect_ratio<1]", options)
    landscape = _with_audio(f"bv[height<={height}]", f"b[height<={height}]", options)
    unknown = _with_audio(f"bv[height<=?{height}]", f"b[height<=?{height}]", options)
    return f"{portrait}/{landscape}/{unknown}"


def _with_audio(video: str, combined: str, options: DownloadOptions) -> str:
    """`video` with the best audio, or one file holding both; dubbed tracks added when asked for.

    The original-language track comes from the "lang" sort; each chosen language adds its own best
    track. When a video lacks one of them, the next alternative keeps just the original.
    """
    plain = f"{video}+{FULL_AUDIO}/{video}+ba/{combined}"
    if not options.multi_audio:
        return plain
    extra = "".join(f"+ba[language^={code}][format_id!*=drc]" for code in options.audio_langs)
    return f"{video}+{FULL_AUDIO}{extra}/{plain}"


def format_sort(options: DownloadOptions) -> str:
    """The -S order that breaks ties between formats the selector allows."""
    if options.kind == "audio":
        return AUDIO_SORT
    if options.container == "webm":
        return "lang,res,vcodec:vp9,acodec:opus"
    return SORT_PROFILES[options.codec_profile]


def folder_template(source: Source) -> str:
    """The folder under the download root: the root itself for one video, a folder of its own for several.

    A video, Short, or song goes straight into the root ("."). A playlist, channel, or profile gets a
    folder named after it, YouTube's as the original script named them. A post or another page gets
    one when it holds several videos, which yt-dlp then reports as a playlist; with one video it names
    no playlist and the "." default keeps the file in the root. An empty default would not: the file
    name would then start with "/" and land at the top of the drive.
    """
    if source.kind in ("video", "short"):
        return "."
    if source.kind == "channel":
        tab = CHANNEL_TABS.get(source.tab, "")
        sub = escape_template(tab) if tab else "%(playlist_title|Videos).100B"
        return f"%(channel,uploader,playlist_uploader|Channel).100B/{sub}"
    if source.kind == "playlist" and source.site == "youtube":
        return "%(playlist).100B"
    if source.kind == "profile":
        return "%(uploader,channel,playlist_uploader,playlist_title|Profile).100B"
    return "%(playlist_title,playlist|.).100B"


def output_template(source: Source, options: DownloadOptions, folder: str = "") -> str:
    """The staged file name: title, ID, and requested profile, renamed to a clean name afterwards.

    `folder` names the folder outright instead of from the video's details (a playlist subscription's
    new uploads, downloaded one link at a time, carry no playlist name).
    """
    prefix = _FILENAME_PREFIX[options.filename_style]
    where = escape_template(folder_name(folder)) if folder else folder_template(source)
    return f"{where}/{prefix}%(title).100B [%(id).64B] (requested-{options.profile}).%(ext)s"


def media_args(source: Source, options: DownloadOptions) -> list[str]:
    """Format, container, subtitle, lyrics, and embedding options."""
    args = ["--format", format_selector(options), "--format-sort", format_sort(options)]
    if options.kind == "audio":
        args += _audio_args(source, options)
    else:
        if options.container == "webm":
            args += ["--merge-output-format", "webm/mkv"]
        else:
            args += ["--merge-output-format", options.container, "--remux-video", options.container]
        if options.multi_audio:
            args.append("--audio-multistreams")
        args += _subtitle_args(options)
        if options.embed_thumbnail and options.container in ("mp4", "mkv"):
            args += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
    # Embedding details also writes each audio track's language, which players show to pick a dub, so
    # several tracks always get it.
    if options.embed_metadata or options.multi_audio:
        args.append("--embed-metadata")
    if options.embed_chapters:
        args.append("--embed-chapters")
    if source.site == "facebook":
        args += ["--replace-in-metadata", "title", _FACEBOOK_COUNTS, ""]
    if options.sponsorblock != "off" and source.site == "youtube":
        flag = "--sponsorblock-mark" if options.sponsorblock == "mark" else "--sponsorblock-remove"
        args += [flag, ",".join(options.sponsorblock_categories)]
    return args


def cuts_segments(source: Source, options: DownloadOptions) -> bool:
    """True when SponsorBlock cuts parts out, which shifts every caption and lyric timing after them."""
    return options.sponsorblock == "remove" and source.site == "youtube"


def _audio_args(source: Source, options: DownloadOptions) -> list[str]:
    """Extraction, bitrate, cover, metadata, and lyrics captions for an audio download."""
    # Before anything reads the title: the file name and the tags both take the song's own.
    args = ["--extract-audio", "--audio-format", options.audio_format,
            "--replace-in-metadata", "title", MUSIC_TITLE_NOISE, ""]
    if not options.lossless_audio:
        args += ["--audio-quality", f"{options.audio_quality}K"]
    if options.embed_thumbnail:
        # WAV can't hold a cover, so the cover is saved beside it as "<name>.jpg".
        args += ["--write-thumbnail" if options.audio_format == "wav" else "--embed-thumbnail",
                 "--convert-thumbnails", "jpg"]
        if options.cover == "square":
            args += ["--postprocessor-args", SQUARE_COVER]
    if options.embed_metadata:
        args += ["--replace-in-metadata", "uploader", ARTIST_SUFFIX, "", "--parse-metadata", _TITLE_TAGS]
    if options.lyrics and not cuts_segments(source, options):
        # Captions become timed lyrics (.lrc) beside the audio; the lyrics step names and checks them.
        # Cut segments would shift every line, so those downloads look lyrics up by length instead.
        args.append("--write-subs")
        if options.auto_subtitles:
            args.append("--write-auto-subs")
        args += ["--sub-langs", options.subtitle_langs, "--convert-subs", "lrc"]
    return args


def _subtitle_args(options: DownloadOptions) -> list[str]:
    """A video's subtitles: embedded, separate files, or both."""
    if options.subtitles == "none":
        return []
    args = ["--write-subs"]
    if options.auto_subtitles:
        args.append("--write-auto-subs")
    args += ["--sub-langs", options.subtitle_langs]
    if options.subtitles in ("sidecar", "both"):
        args += ["--convert-subs", options.subtitle_format]
    if options.subtitles in ("embed", "both"):
        args.append("--embed-subs")
    if options.subtitles == "embed":
        args += ["--compat-options", "no-keep-subs"]
    return args


def playlist_list_args(lists: Path) -> list[str]:
    """Have yt-dlp write each playlist's details, with every video in it, before the first download.

    Only the playlist file is written: the empty "infojson" template leaves out one per video, and
    --no-clean-info-json keeps the list of videos, which cleaning would drop. yt-dlp announces the file
    with "[info] Writing playlist metadata as JSON to: <path>" (read in progress.py). A channel's tabs
    each get a file of their own, so the name carries the title as well as the ID.
    """
    template = escape_template(str(lists)) + "/%(id).40B %(title).60B.%(ext)s"
    return ["--write-info-json", "--no-clean-info-json", "--no-embed-info-json",
            "--output", "infojson:", "--output", f"pl_infojson:{template}"]


def run_marker() -> str:
    """A marker for one run's lines, which no site can know in advance."""
    return f"@@gfgr-{secrets.token_hex(8)}:"


def structured_output_args(journal: Path, marker: str = MARKER) -> list[str]:
    """Progress, item, and finished-file lines the app parses, plus yt-dlp's own file journal."""
    file_line = f"%(.{{{_FILE_FIELDS}}})j"
    return [
        "--progress",
        "--progress-delta", "0.5",
        "--no-simulate",
        "--progress-template", f"download:{marker}{_DOWNLOAD_PROGRESS}",
        "--progress-template", f"postprocess:{marker}{_POSTPROCESS_PROGRESS}",
        *print_arg("video", f"{marker}item %(.{{{_ITEM_FIELDS}}})j"),
        *print_arg("video", f"{marker}parts %(requested_formats.:.{{format_id,vcodec,acodec,filesize,filesize_approx}})j"),
        *print_arg("after_move", f"{marker}file {file_line}"),
        "--print-to-file", f"after_move:{file_line}", escape_template(str(journal)),
    ]


def skip_filter(skip_ids: Sequence[str]) -> list[str]:
    """A --match-filters that leaves out items known to fail for good (private, removed)."""
    ids = [item for item in dict.fromkeys(skip_ids) if item and all(ch.isalnum() or ch in "-_" for ch in item)]
    if not ids:
        return []
    return ["--match-filters", " & ".join(f"id!={item}" for item in ids[:MAX_SKIP_FILTERS])]


def download_command(url: str, source: Source, options: DownloadOptions, tools: ToolSet, paths: RunPaths,
                     auth: Auth | None = None, skip_ids: Sequence[str] = (), urls: Sequence[str] = (),
                     folder: str = "", marker: str = MARKER) -> list[str]:
    """One download attempt: resumable, archived, and reporting progress as JSON lines.

    `urls`, when given, are downloaded in place of `url` (a subscription's new uploads); over
    MAX_INLINE_URLS they go through a batch file the caller writes (see url_args). `folder` names the
    folder outright (see output_template). `marker` starts the lines the app reads (see run_marker).
    """
    root = paths.root
    command = base_args(tools, paths.cache_dir) + retry_args() + [
        "--yes-playlist" if source.is_collection else "--no-playlist",
        "--no-abort-on-error",
        "--abort-on-unavailable-fragments",
        "--continue",
        "--part",
        "--no-overwrites",
        # Downloading again past the archive still keeps one, for this run only, so a restart after a
        # stall doesn't fetch what the run already saved.
        "--download-archive", str(paths.session_archive if options.ignore_archive else paths.archive),
        "--paths", str(root),
        "--paths", f"temp:{paths.incomplete}",
        "--output", output_template(source, options, folder),
        "--http-chunk-size", "8M",
        "--concurrent-fragments", str(options.fragments),
    ]
    command += media_args(source, options)
    if options.kind == "audio":
        # ffmpeg's own progress, written as it converts; forward slashes, since yt-dlp splits these
        # arguments like a shell, and quotes for the spaces in the app's data folder.
        command += ["--postprocessor-args", f'ExtractAudio+ffmpeg_o:-progress "{paths.convert_progress.as_posix()}"']
    command += network_args(options)
    command += auth_args(auth)
    if options.items:
        command += ["--playlist-items", options.items]
    if options.live_from_start:
        command.append("--live-from-start")
    if options.wait_for_video:
        command += ["--wait-for-video", "15-120"]
    command += skip_filter(skip_ids)
    command += structured_output_args(paths.journal, marker)
    command += playlist_list_args(paths.lists)
    return command + (url_args(urls, paths.job_dir)[0] if urls else ["--", url])


def analyze_command(url: str, tools: ToolSet, cache_dir: Path, auth: Auth | None = None,
                    options: DownloadOptions | None = None, single: bool = False) -> list[str]:
    """Read a link's details without downloading: one JSON document, playlists listed flat."""
    command = base_args(tools, cache_dir) + [
        "--dump-single-json",
        "--flat-playlist",
        "--no-playlist" if single else "--yes-playlist",
        "--extractor-retries", "3",
    ]
    if options is not None:
        command += network_args(options)
    command += auth_args(auth)
    return command + ["--", url]


def check_command(urls: Sequence[str], tools: ToolSet, archive: Path, cache_dir: Path, job_dir: Path,
                  auth: Auth | None = None, newest: int = 60,
                  options: DownloadOptions | None = None, marker: str = MARKER,
                  whole: bool = False) -> tuple[list[str], str]:
    """List a subscription's newest uploads that aren't in its archive, without downloading.

    Channel tabs are newest first, so the scan stops at the first archived item; yt-dlp then exits
    with status 101, which means success here. A playlist (`whole`) is read to its end, up to
    `newest` entries: its new videos are usually added last. Returns (command, batch file text or "").
    """
    command = base_args(tools, cache_dir) + [
        "--flat-playlist",
        "--lazy-playlist",
        "--yes-playlist",
        "--playlist-items", f"1:{max(newest, 1)}",
        "--download-archive", str(archive),
        *(() if whole else ("--break-on-existing", "--break-per-input")),
        "--sleep-requests", "1",
        *print_arg("video", f"{marker}entry %(.{{{_ENTRY_FIELDS}}})j"),
        *print_arg("playlist", f"{marker}pl %(.{{id,title,uploader,channel,webpage_url,extractor_key}})j"),
    ]
    if options is not None:
        command += network_args(options)
    command += auth_args(auth)
    links, batch = url_args(urls, job_dir)
    return command + links, batch


def account_check_command(url: str, tools: ToolSet, cache_dir: Path, auth: Auth) -> list[str]:
    """Read the first entry of a list only a signed-in account can see (YouTube's Watch later).

    Exit status 0 means the sign-in works; nothing is downloaded.
    """
    return base_args(tools, cache_dir) + [
        "--flat-playlist",
        "--playlist-items", "1",
        "--skip-download",
        "--extractor-retries", "2",
    ] + auth_args(auth) + ["--", url]


# yt-dlp's exit status when --break-on-existing stopped at an archived item.
EXIT_BREAK_ON_EXISTING = 101
