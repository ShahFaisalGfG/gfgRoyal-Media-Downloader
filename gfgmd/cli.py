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
from pathlib import Path
from typing import Any, Sequence

from gfgmd.config.defaults import AppInfo, DownloadDefaults, FormatDefaults
from gfgmd.core.archive import archive_path
from gfgmd.core.command import Auth, RunPaths
from gfgmd.core.jobs import JobExecutor, JobResult, JobSpec
from gfgmd.core.lyrics import fetch_json
from gfgmd.core.naming import normalize_downloads
from gfgmd.core.options import DownloadOptions, check_proxy
from gfgmd.core.progress import Event
from gfgmd.core.sources import Source, canonical_url, source_from_url
from gfgmd.core.tools import ToolSet, ToolsMissing, resolve_tools
from gfgmd.utils.format import format_bytes, format_duration
from gfgmd.utils.paths import cache_dir, default_audio_root, default_download_root, tools_dir

EXIT_OK, EXIT_FAILED, EXIT_INVALID, EXIT_STOPPED = 0, 1, 2, 130
_RATE = re.compile(r"^(\d+(?:\.\d+)?)([KMG]?)(?:i?B)?(?:/s)?$", re.IGNORECASE)
_PROGRESS_EVERY = 2.0


def positive_int(value: str) -> int:
    """Parse a positive integer for a command line option."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def nonnegative_int(value: str) -> int:
    """Parse a nonnegative integer for a command line option."""
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return number


def fragment_count(value: str) -> int:
    """Parse a supported fragment concurrency value."""
    range_error = f"expected an integer from 1 to {DownloadDefaults.MAX_FRAGMENTS}"
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
        raise argparse.ArgumentTypeError("expected a speed such as 500K or 2M")
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
                        help=f"download root (default: ~/Videos/{DownloadDefaults.FOLDER_NAME})")
    parser.add_argument("--max-attempts", type=nonnegative_int, default=0, metavar="N",
                        help="download attempts; 0 retries temporary failures indefinitely (default: 0)")
    parser.add_argument("--retry-delay", type=positive_int, default=DownloadDefaults.RETRY_DELAY, metavar="SECONDS",
                        help="first wait between attempts; doubles up to five minutes (default: 10)")
    parser.add_argument("-c", "--concurrent-fragments", type=fragment_count, default=DownloadDefaults.AUTO_FRAGMENTS,
                        metavar="N", help="simultaneous HLS/DASH fragments, 1-16 (default: 8)")
    parser.add_argument("--cookies", type=Path, help="Netscape cookies file for links that need sign-in")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[:PROFILE]",
                        help="read sign-in cookies from a browser, such as firefox")
    media = parser.add_argument_group("format")
    media.add_argument("--audio", choices=FormatDefaults.AUDIO_FORMATS, nargs="?", const="mp3",
                       help="save audio only, as MP3 unless a format is named (best keeps the site's own audio)")
    media.add_argument("--audio-quality", type=int, choices=FormatDefaults.AUDIO_QUALITIES,
                       default=FormatDefaults.DEFAULT_AUDIO_QUALITY, metavar="KBPS",
                       help="bitrate for MP3, M4A, Opus, and OGG audio (default: 320)")
    media.add_argument("--cover", choices=FormatDefaults.COVER_SHAPES, default="square",
                       help="shape of the cover embedded in audio files (default: square)")
    media.add_argument("--no-cover", action="store_true", help="don't embed the thumbnail as the audio cover")
    media.add_argument("--no-lyrics", action="store_true", help="don't save timed lyrics (.lrc) with audio")
    media.add_argument("--no-online-lyrics", action="store_true",
                       help="use only the site's captions for lyrics, never an LRCLIB lookup")
    media.add_argument("--audio-langs", metavar="LANGS",
                       help="keep these dubbed audio tracks next to the original, such as es,pt-BR (MP4 or MKV)")
    media.add_argument("--container", choices=FormatDefaults.CONTAINERS, default="mp4",
                       help="video container (default: mp4)")
    media.add_argument("--codec", choices=FormatDefaults.CODEC_PROFILES, default="balanced",
                       help="codec preference (default: balanced, the original script's order)")
    media.add_argument("--subs", metavar="LANGS", help="download subtitles in these languages, such as en.*,ur")
    media.add_argument("--auto-subs", action="store_true", help="include automatic captions")
    media.add_argument("--embed-subs", action="store_true", help="embed subtitles instead of separate files")
    media.add_argument("--keep-subs", action="store_true", help="embed subtitles and keep the separate files too")
    media.add_argument("--sub-format", choices=FormatDefaults.SUBTITLE_FORMATS, default="srt",
                       help="format of separate subtitle files (default: srt)")
    media.add_argument("--embed", action="store_true", help="embed the thumbnail, metadata, and chapters")
    media.add_argument("--sponsorblock", choices=("mark", "remove"),
                       help="mark or cut SponsorBlock segments (YouTube)")
    media.add_argument("--filename-style", choices=DownloadDefaults.FILENAME_STYLES, default="title-quality",
                       help="file name style (default: title-quality)")
    network = parser.add_argument_group("network")
    network.add_argument("--limit-rate", type=rate_limit, metavar="RATE", help="speed limit, such as 2M")
    network.add_argument("--proxy", type=proxy_url, metavar="URL", help="http://, https://, or socks5:// proxy")
    network.add_argument("--force-ipv4", action="store_true", help="connect over IPv4 only")
    selection = parser.add_argument_group("selection")
    selection.add_argument("--items", metavar="SPEC", help="playlist items to download, such as 1:5,8")
    selection.add_argument("--live-from-start", action="store_true", help="record live streams from the start")
    selection.add_argument("--wait-for-video", action="store_true", help="wait for scheduled streams to begin")
    selection.add_argument("--strict", action="store_true",
                           help="exit with status 1 when any item was skipped (private, removed, ...)")
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
    """Prints item starts, progress at most every two seconds, saved files, and warnings."""

    def __init__(self, executor_ref: list[JobExecutor]) -> None:
        self._executor_ref = executor_ref
        self._last = 0.0

    def __call__(self, event: Event) -> None:
        if event.kind == "item":
            title = event.data.get("title") or event.data.get("id") or ""
            print(f"Downloading: {title}", flush=True)
        elif event.kind == "dl" and self._executor_ref:
            now = time.monotonic()
            if now - self._last >= _PROGRESS_EVERY:
                self._last = now
                print(_progress_line(self._executor_ref[0]), flush=True)
        elif event.kind == "error":
            print(f"Error: {event.text}", file=sys.stderr, flush=True)
        elif event.kind == "warning" and "Falling back on generic" not in event.text:
            print(f"Warning: {event.text}", file=sys.stderr, flush=True)


def _progress_line(executor: JobExecutor) -> str:
    snap = executor.snapshot()
    parts = []
    if snap.item_count > 1:
        parts.append(f"[{snap.item_index}/{snap.item_count}]")
    parts.append(snap.stage)
    if snap.total:
        parts.append(f"{snap.item_fraction * 100:.0f}% of {format_bytes(snap.total)}")
    elif snap.downloaded:
        parts.append(format_bytes(snap.downloaded))
    if snap.speed:
        parts.append(f"{format_bytes(int(snap.speed))}/s")
    if snap.eta >= 0:
        parts.append(f"{format_duration(snap.eta)} left")
    return "  ".join(parts)


def _on_file(_info: dict[str, Any], path: Path) -> None:
    print(f"Saved: {path}", flush=True)


def run(argv: Sequence[str] | None = None) -> int:
    """Download the link, retrying temporary failures until it succeeds or the attempt limit is reached."""
    args = parse_args(argv)
    try:
        source = source_from_url(args.url)
        options = options_from_args(args)
        tools = find_dependencies()
        if args.cookies is not None and not args.cookies.is_file():
            raise ValueError(f"Cookies file does not exist: {args.cookies}")
        default_root = default_audio_root() if options.kind == "audio" else default_download_root()
        output_root = (args.output_dir or default_root).resolve()
        (output_root / ".archives").mkdir(parents=True, exist_ok=True)
    except (OSError, ToolsMissing, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID

    auth = None
    if args.cookies is not None:
        auth = Auth(cookies_file=str(args.cookies.resolve()))
    elif args.cookies_from_browser:
        auth = Auth(browser=args.cookies_from_browser)
    archive = archive_path(output_root, source, options.profile)
    paths = RunPaths(output_root, archive, job_folder(output_root, source, options.profile), cache_dir())
    spec = JobSpec(canonical_url(source, args.url), source, options, paths, auth, args.max_attempts,
                   args.retry_delay)
    holder: list[JobExecutor] = []
    executor = JobExecutor(spec, lambda: tools, on_file=_on_file, on_event=_Reporter(holder), lyrics_fetch=fetch_json)
    holder.append(executor)
    print(f"Downloading {args.url}", flush=True)
    result = executor.run(sleep=_sleep_reporting(executor))
    if options.kind == "video" and options.filename_style == "title-quality":
        try:
            normalize_downloads(output_root, archive, tools.ffprobe)
        except (OSError, UnicodeError, RuntimeError) as exc:
            print(f"Could not clean video filenames: {exc}", file=sys.stderr)
    return _report(result, output_root, args.strict)


def _sleep_reporting(executor: JobExecutor):
    def wait(seconds: float) -> bool:
        print(f"Download attempt {executor.attempt} had errors. Retrying in {int(seconds)} seconds.", flush=True)
        time.sleep(seconds)
        return False
    return wait


def _report(result: JobResult, output_root: Path, strict: bool) -> int:
    for failure in result.skipped:
        print(f"Skipped {failure.item_id}: {failure.category.message}", file=sys.stderr)
    for error in result.rename_errors:
        print(f"Could not clean a filename: {error}", file=sys.stderr)
    if result.state == "done":
        print(f"Download complete ({result.message}). Files are under {output_root}")
        return EXIT_FAILED if strict and result.skipped else EXIT_OK
    if result.state == "failed" and result.failure is not None and result.failure.category.key == "tools":
        print(f"Error: {result.failure.text}", file=sys.stderr)
        return EXIT_INVALID
    message = result.failure.category.message if result.failure else "The download failed"
    if result.state == "needs_auth":
        message += " (use --cookies or --cookies-from-browser)"
    print(f"Download still has errors after {result.attempts} attempts: {message}", file=sys.stderr)
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
