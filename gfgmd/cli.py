"""gfgmd: download videos, playlists, channels, and live streams from the command line.

Exit status: 0 when every available item was saved (items that can never download, such as private
videos, are listed but don't fail the run unless --strict), 1 when failures remain after
--max-attempts, 2 when the link, the tools, or the folders can't be used, 130 when stopped with
Ctrl+C. Stopping keeps partial files, and the same command resumes later.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Sequence

from gfgmd.config.defaults import AppInfo, DownloadDefaults, FormatDefaults
from gfgmd.core import web
from gfgmd.core.archive import archive_path
from gfgmd.core.command import Auth, RunPaths
from gfgmd.core.errors import CATEGORIES, Category, Failure, classify
from gfgmd.core.jobs import JobExecutor, JobResult, JobSpec
from gfgmd.core.lyrics import fetch_json
from gfgmd.core.naming import normalize_downloads
from gfgmd.core.options import DownloadOptions, check_proxy
from gfgmd.core.progress import Event, Snapshot
from gfgmd.core.sources import Source, as_link, canonical_url, source_from_url
from gfgmd.core.tools import ToolSet, ToolsMissing, resolve_tools
from gfgmd.utils.format import format_bytes, format_time_left, format_wait, media_noun
from gfgmd.utils.paths import cache_dir, default_audio_root, default_download_root, tools_dir

EXIT_OK, EXIT_FAILED, EXIT_INVALID, EXIT_STOPPED = 0, 1, 2, 130
_RATE = re.compile(r"^(\d+(?:\.\d+)?)([KMG]?)(?:i?B)?(?:/s)?$", re.IGNORECASE)
_PROGRESS_EVERY = 2.0
_TOOLS_MISSING = "The download tools aren't installed. Open the app once to install them."
_TOOLS_BROKEN = "The download tools are missing or didn't start. Open the app once to install them again."
_SIGN_IN = "Use --cookies or --cookies-from-browser to sign in."
_ELSEWHERE = "Use --output-dir to save somewhere else."
# The command line's way out where the app's message points at a control of its window (Sign in,
# Choose folder, Update tools, waiting for a stream).
_CLI_HINTS = {
    "auth_required": _SIGN_IN, "cookies_stale": _SIGN_IN, "private_signin": _SIGN_IN,
    "disk_full": _ELSEWHERE, "access_denied": _ELSEWHERE, "folder_missing": _ELSEWHERE,
    "upcoming": "Add --wait-for-video to wait for it.",
    "extractor_broken": "Open the app to update the download tools.",
}


def _with_hint(category: Category, text: str) -> str:
    """The message with the command line's option for it added."""
    hint = _CLI_HINTS.get(category.key, "")
    return f"{text} {hint}" if hint else text


def positive_int(value: str) -> int:
    """Parse a positive integer for a command line option."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number, 1 or more") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a whole number, 1 or more")
    return number


def nonnegative_int(value: str) -> int:
    """Parse a nonnegative integer for a command line option."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number, 0 or more") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a whole number, 0 or more")
    return number


def fragment_count(value: str) -> int:
    """Parse how many parts of a video download at once."""
    range_error = f"must be a whole number from 1 to {DownloadDefaults.MAX_FRAGMENTS}"
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(range_error) from exc
    if not 1 <= count <= DownloadDefaults.MAX_FRAGMENTS:
        raise argparse.ArgumentTypeError(range_error)
    return count


def rate_limit(value: str) -> int:
    """Parse a speed such as 500K, 2M, or 1.5MiB/s into bytes per second (binary units)."""
    match = _RATE.fullmatch(value.strip())
    if match is None:
        raise argparse.ArgumentTypeError("must be a speed such as 500K or 2M")
    number, unit = float(match.group(1)), match.group(2).upper()
    scaled = int(number * {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[unit])
    if scaled < 1:
        raise argparse.ArgumentTypeError("the speed must be above zero")
    return scaled


def proxy_url(value: str) -> str:
    """Parse a proxy URL."""
    try:
        return check_proxy(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    """The command-line options (the original script's options keep their names and defaults)."""
    parser = argparse.ArgumentParser(prog=AppInfo.CLI_NAME, description=AppInfo.APP_DESCRIPTION)
    parser.add_argument("--version", action="version", version=f"{AppInfo.CLI_NAME} {AppInfo.APP_VERSION}")
    parser.add_argument("url", help="link to a video, Short, playlist, channel, or a page on another site")
    parser.add_argument("-r", "--resolution", type=nonnegative_int, default=1080, metavar="HEIGHT",
                        help="highest resolution on the shorter side, 0 for the best (default: 1080)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help=f"folder to save into (default: Videos\\{DownloadDefaults.FOLDER_NAME}, "
                             f"or Music\\{DownloadDefaults.FOLDER_NAME} with --audio)")
    parser.add_argument("--max-attempts", type=nonnegative_int, default=0, metavar="N",
                        help="how many times to try; 0 keeps trying until it works or you press Ctrl+C (default: 0)")
    parser.add_argument("--retry-delay", type=positive_int, default=DownloadDefaults.RETRY_DELAY, metavar="SECONDS",
                        help="first wait between attempts; doubles up to five minutes (default: 10)")
    parser.add_argument("-c", "--concurrent-fragments", type=fragment_count, default=DownloadDefaults.AUTO_FRAGMENTS,
                        metavar="N", help="how many parts of a video download at once, 1-16 (default: 8)")
    parser.add_argument("--cookies", type=Path,
                        help="a cookies.txt sign-in file exported from your browser, for links that need sign-in")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[:PROFILE]",
                        help="use your sign-in from a browser, such as firefox")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="also show the download tools' warnings and their own error text")
    media = parser.add_argument_group("format")
    media.add_argument("--audio", choices=FormatDefaults.AUDIO_FORMATS, nargs="?", const="mp3",
                       help="save audio only, as MP3 unless a format is named (best keeps the site's own audio)")
    media.add_argument("--audio-quality", type=int, choices=FormatDefaults.AUDIO_QUALITIES,
                       default=FormatDefaults.DEFAULT_AUDIO_QUALITY, metavar="KBPS",
                       help="audio quality in kbps for MP3, M4A, Opus, and OGG (default: 320)")
    media.add_argument("--cover", choices=FormatDefaults.COVER_SHAPES, default="square",
                       help="shape of the cover put in audio files (default: square)")
    media.add_argument("--no-cover", action="store_true",
                       help="don't put the thumbnail in audio files as their cover")
    media.add_argument("--no-lyrics", action="store_true",
                       help="don't save lyrics that follow along with the song")
    media.add_argument("--no-online-lyrics", action="store_true",
                       help="use only the site's captions for lyrics, never an online lyrics lookup")
    media.add_argument("--audio-langs", metavar="LANGS",
                       help="keep these dubbed languages next to the original, such as es,pt-BR (MP4 or MKV)")
    media.add_argument("--container", choices=FormatDefaults.CONTAINERS, default="mp4",
                       help="video file type (default: mp4)")
    media.add_argument("--codec", choices=FormatDefaults.CODEC_PROFILES, default="balanced",
                       help="compatible plays everywhere, best allows newer formats that older devices may not "
                            "play (default: balanced, highest resolution first)")
    media.add_argument("--subs", metavar="LANGS", help="download subtitles in these languages, such as en.*,ur")
    media.add_argument("--auto-subs", action="store_true", help="include automatic captions")
    media.add_argument("--embed-subs", action="store_true",
                       help="put subtitles inside the video instead of separate files")
    media.add_argument("--keep-subs", action="store_true",
                       help="put subtitles inside the video and keep the separate files too")
    media.add_argument("--sub-format", choices=FormatDefaults.SUBTITLE_FORMATS, default="srt",
                       help="file type of separate subtitle files (default: srt)")
    media.add_argument("--embed", action="store_true",
                       help="put the thumbnail, title and details, and chapters inside the file")
    media.add_argument("--sponsorblock", choices=("mark", "remove"),
                       help="mark or cut the sponsor parts SponsorBlock lists (YouTube)")
    media.add_argument("--filename-style", choices=DownloadDefaults.FILENAME_STYLES, default="title-quality",
                       help="file name style (default: title-quality)")
    network = parser.add_argument_group("network")
    network.add_argument("--limit-rate", type=rate_limit, metavar="RATE", help="speed limit, such as 2M")
    network.add_argument("--proxy", type=proxy_url, metavar="URL", help="proxy address, such as http://proxy:8080")
    network.add_argument("--force-ipv4", action="store_true", help="connect over IPv4 only")
    selection = parser.add_argument_group("selection")
    selection.add_argument("--items", metavar="SPEC",
                           help="which playlist videos to download, by number, such as 1:5,8")
    selection.add_argument("--live-from-start", action="store_true", help="record live streams from the start")
    selection.add_argument("--wait-for-video", action="store_true", help="wait for scheduled streams to begin")
    selection.add_argument("--strict", action="store_true",
                           help="report a failure (exit status 1) when any video couldn't be downloaded "
                                "(private, removed, ...)")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the link, format, output, and retry settings."""
    return build_parser().parse_args(argv)


def options_from_args(args: argparse.Namespace) -> DownloadOptions:
    """The download options the command line asked for."""
    audio = bool(args.audio)
    langs = tuple(code.strip() for code in (args.audio_langs or "").split(",") if code.strip())
    if args.keep_subs:
        subtitles = "both"
    elif args.subs:
        subtitles = "embed" if args.embed_subs else "sidecar"
    else:
        subtitles = "none"
    return DownloadOptions(
        kind="audio" if audio else "video",
        max_height=args.resolution,
        container=args.container,
        codec_profile=args.codec,
        audio_tracks="languages" if langs else "original",
        audio_langs=langs,
        audio_format=args.audio or "mp3",
        audio_quality=args.audio_quality,
        cover=args.cover,
        subtitles=subtitles,
        subtitle_format=args.sub_format,
        subtitle_langs=args.subs or "en.*",
        auto_subtitles=args.auto_subs,
        lyrics=not args.no_lyrics,
        lyrics_online=not args.no_online_lyrics,
        # Audio files get their cover and tags unless asked not to; video embeds them with --embed.
        embed_thumbnail=(not args.no_cover) if audio else args.embed,
        embed_metadata=audio or args.embed,
        embed_chapters=args.embed,
        sponsorblock=args.sponsorblock or "off",
        filename_style=args.filename_style,
        fragments=args.concurrent_fragments,
        limit_rate=args.limit_rate or 0,
        proxy=args.proxy or "",
        force_ipv4=args.force_ipv4,
        items=args.items or "",
        live_from_start=args.live_from_start,
        wait_for_video=args.wait_for_video,
    ).validate()


def job_folder(output_root: Path, source: Source, profile: str) -> Path:
    """The command-line run's scratch folder: one per link and profile, so a rerun resumes it."""
    key = hashlib.sha256(f"{source.kind}:{source.source_id}:{profile}".encode("utf-8")).hexdigest()[:16]
    return output_root / ".gfgmd" / "jobs" / key


def find_dependencies() -> ToolSet:
    """The app's managed tools, or the programs on PATH."""
    return resolve_tools("managed", tools_dir())


class _Reporter:
    """Prints each video as it starts, progress at most every two seconds, and problems in plain words.

    The download tools' own error text and their warnings print only with --verbose.
    """

    def __init__(self, executor_ref: list[JobExecutor], spec: JobSpec, verbose: bool) -> None:
        self._executor_ref = executor_ref
        self._kind = spec.options.kind
        self._url = spec.url
        self._signed_in = spec.auth is not None
        self._single = not spec.source.is_collection
        self._verbose = verbose
        self._last = 0.0
        # Titles by video ID, so a problem with a video names it; and the problems said so far, which
        # the closing line doesn't repeat.
        self.titles: dict[str, str] = {}
        self.said: set[str] = set()

    def __call__(self, event: Event) -> None:
        if event.kind == "item":
            item_id, title = str(event.data.get("id") or ""), str(event.data.get("title") or "")
            if item_id and title:
                self.titles[item_id] = title
            print(f"Downloading: {title or 'Untitled ' + media_noun(self._kind)}", flush=True)
        elif event.kind == "dl" and self._executor_ref:
            now = time.monotonic()
            if now - self._last >= _PROGRESS_EVERY:
                self._last = now
                print(_progress_line(self._executor_ref[0].snapshot(), self._kind), flush=True)
        elif event.kind == "error":
            item_id = str(event.data.get("id") or "")
            failure = classify(event.text, item_id, self._signed_in, self._single)
            self.said.add(failure.category.message)
            print(self.describe(item_id, _with_hint(failure.category, failure.category.message)), file=sys.stderr,
                  flush=True)
            if self._verbose:
                print(f"  Details: {event.text}", file=sys.stderr, flush=True)
        elif event.kind == "warning" and self._verbose and "Falling back on generic" not in event.text:
            print(f"Warning: {event.text}", file=sys.stderr, flush=True)

    def describe(self, item_id: str, message: str) -> str:
        """A problem with the download, naming the video when its title is known."""
        title = self.titles.get(item_id, "")
        if not item_id and self._executor_ref:
            title = self._executor_ref[0].snapshot().title  # a step on the video in progress, such as converting
        if title:
            return f'Couldn\'t download "{title}": {message}'
        if self._single:
            return f"Couldn't download the {media_noun(self._kind)}: {message}"
        if item_id and item_id not in self._url:
            return f"Couldn't download one of the {media_noun(self._kind, 2)}: {message}"
        return f"Couldn't download from this link: {message}"


def _progress_line(snap: Snapshot, kind: str) -> str:
    """One progress line: "Video 2 of 8  Downloading  45% of 40.0 MB  2.1 MB/s  about 1 minute left"."""
    parts = []
    if snap.item_count > 1 and snap.item_index > 0:
        parts.append(f"{media_noun(kind).capitalize()} {snap.item_index} of {snap.item_count}")
    parts.append(snap.stage)
    if snap.total and not snap.size_guessed:
        parts.append(f"{snap.item_fraction * 100:.0f}% of {format_bytes(snap.total)}")
    elif snap.downloaded:
        parts.append(format_bytes(snap.downloaded))
    if snap.speed:
        parts.append(f"{format_bytes(int(snap.speed))}/s")
    if snap.eta >= 0:
        parts.append(format_time_left(snap.eta))
    return "  ".join(parts)


def _on_file(_info: dict[str, Any], path: Path) -> None:
    print(f"Saved: {path}", flush=True)


def _invalid(message: str, detail: str = "") -> int:
    """Say why the download can't start or go on (with the details under it, for --verbose)."""
    print(message, file=sys.stderr)
    if detail:
        print(f"  Details: {detail}", file=sys.stderr)
    return EXIT_INVALID


def run(argv: Sequence[str] | None = None) -> int:
    """Download the link, retrying temporary failures until it succeeds or the attempt limit is reached."""
    args = parse_args(argv)
    url = as_link(args.url)
    try:
        source = source_from_url(url)
        options = options_from_args(args)
    except ValueError as exc:
        return _invalid(str(exc))
    web.use_proxy(options.proxy)  # the lyrics lookup goes through --proxy too
    if args.cookies is not None and not args.cookies.is_file():
        return _invalid(f"The sign-in file wasn't found: {args.cookies}")
    try:
        tools = find_dependencies()
    except ToolsMissing as exc:
        return _invalid(_TOOLS_MISSING, f"Missing: {', '.join(exc.missing)}" if args.verbose else "")
    try:
        default_root = default_audio_root() if options.kind == "audio" else default_download_root()
        output_root = (args.output_dir or default_root).resolve()
        (output_root / ".archives").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        folder = args.output_dir or "the download folder"
        return _invalid(f"Can't save to {folder}. Choose another folder with --output-dir.",
                        str(exc) if args.verbose else "")

    auth = None
    if args.cookies is not None:
        auth = Auth(cookies_file=str(args.cookies.resolve()))
    elif args.cookies_from_browser:
        auth = Auth(browser=args.cookies_from_browser)
    archive = archive_path(output_root, source, options.profile)
    paths = RunPaths(output_root, archive, job_folder(output_root, source, options.profile), cache_dir())
    spec = JobSpec(canonical_url(source, url), source, options, paths, auth, args.max_attempts,
                   args.retry_delay)
    holder: list[JobExecutor] = []
    reporter = _Reporter(holder, spec, args.verbose)
    executor = JobExecutor(spec, lambda: tools, on_file=_on_file, on_event=reporter, lyrics_fetch=fetch_json)
    holder.append(executor)
    print(f"Downloading {url}", flush=True)
    result = executor.run(sleep=_sleep_reporting(executor))
    if options.kind == "video" and options.filename_style == "title-quality":
        try:
            normalize_downloads(output_root, archive, tools.ffprobe)
        except (OSError, UnicodeError, RuntimeError) as exc:
            print("Some video names couldn't be tidied up; the files are saved.", file=sys.stderr)
            if args.verbose:
                print(f"  Details: {exc}", file=sys.stderr)
    return _report(result, output_root, args.strict, options.kind, reporter, args.verbose)


def _sleep_reporting(executor: JobExecutor) -> Callable[[float], bool]:
    """The wait between attempts, saying when the next one starts."""
    def wait(seconds: float) -> bool:
        print(f"Attempt {executor.retries} didn't finish. Trying again {format_wait(seconds)}.", flush=True)
        time.sleep(seconds)
        return False
    return wait


def _report(result: JobResult, output_root: Path, strict: bool, kind: str = "video",
            reporter: _Reporter | None = None, verbose: bool = False) -> int:
    """Say how the download ended; returns the exit status for it."""
    titles = reporter.titles if reporter else {}
    said = reporter.said if reporter else set()
    for failure in result.skipped:
        title = titles.get(failure.item_id, "")
        name = f'"{title}"' if title else f"a {media_noun(kind)}"
        print(f"Skipped {name}: {failure.category.final}", file=sys.stderr)
    for error in result.rename_errors:
        name, _, detail = error.partition(": ")
        print(f'"{name}" kept its original file name.', file=sys.stderr)
        if verbose and detail:
            print(f"  Details: {detail}", file=sys.stderr)
    if result.state == "done":
        print(f"Finished: {result.message}. The files are in {output_root}")
        return EXIT_FAILED if strict and result.skipped else EXIT_OK
    if result.state == "stopped":
        print("Stopped. Run the same command to resume later.", file=sys.stderr)
        return EXIT_STOPPED
    failure = result.failure or Failure(CATEGORIES["unknown"], "")
    if failure.category.key == "tools":
        return _invalid(_TOOLS_BROKEN, failure.text if verbose else "")
    message = _with_hint(failure.category, failure.category.final)
    tries = f" after {result.attempts} attempts" if result.attempts > 1 else ""
    if failure.category.final in said:
        print(f"The download didn't finish{tries}.", file=sys.stderr)  # the reason was the line above
    else:
        print(f"The download didn't finish{tries}: {message}", file=sys.stderr)
    return EXIT_FAILED


def console_safe() -> None:
    """Let titles in any script print: characters the console's code page lacks become "?" instead of
    an error (a title with "＊" stopped a finished download from reporting, piped on Windows)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the downloader and turn Ctrl+C into a stop that can be resumed."""
    console_safe()
    try:
        return run(argv)
    except KeyboardInterrupt:
        print("\nStopped. Run the same command to resume later.", file=sys.stderr)
        return EXIT_STOPPED


if __name__ == "__main__":
    raise SystemExit(main())
