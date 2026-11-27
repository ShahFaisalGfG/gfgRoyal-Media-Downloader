"""Search YouTube or YouTube Music from the link box: the yt-dlp command, and its results as they arrive.

Videos come from YouTube's own search (title, channel, length, views, and thumbnail for each). Songs
come from YouTube Music's song results, which give only a title; the thumbnail is the video's own,
and the app fills in the artist from YouTube's oEmbed page (see quick_info) as the results show.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

from gfgmd.core.analyze import AnalyzeError
from gfgmd.core.command import list_command, run_marker
from gfgmd.core.errors import classify
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import parse_line, pick_thumbnail
from gfgmd.core.runner import Runner, run_to_completion
from gfgmd.core.tools import ToolSet

# Results on the first search, and after "More results".
FIRST_RESULTS = 20
MORE_RESULTS = 50
MAX_QUERY = 200


@dataclass(frozen=True)
class SearchResult:
    """One video or song a search found."""

    id: str
    title: str
    url: str
    thumbnail: str
    channel: str = ""
    duration: float = 0.0
    views: int = 0
    live_status: str = ""


def clean_query(query: str) -> str:
    """The words as searched: single spaces, at most MAX_QUERY characters."""
    return " ".join(query.split())[:MAX_QUERY]


def search_target(query: str, music: bool, limit: int) -> str:
    """What yt-dlp is given: "ytsearchN:words" for videos, YouTube Music's song search for songs."""
    words = clean_query(query)
    if music:
        return f"https://music.youtube.com/search?q={quote_plus(words)}#songs"
    return f"ytsearch{limit}:{words}"


def search_command(query: str, music: bool, limit: int, tools: ToolSet, cache_dir: Path,
                   options: DownloadOptions | None = None, marker: str = "") -> list[str]:
    """Read the search results flat, one marked line each, as a list read does (see list_command).
    Only the first `limit` are read: YouTube Music's search pages on until its results run out."""
    command = list_command(search_target(query, music, limit), tools, cache_dir, None, options, marker or run_marker())
    split = command.index("--")
    return command[:split] + ["--playlist-items", f"1:{limit}"] + command[split:]


def result_from(data: dict[str, Any], music: bool) -> SearchResult | None:
    """One listed entry as a result; None for one without an ID (a channel or a playlist row)."""
    video_id = str(data.get("id") or "")
    if not video_id or str(data.get("_type") or "url") not in ("url", "video"):
        return None
    site = "https://music.youtube.com" if music else "https://www.youtube.com"
    views = data.get("view_count")
    duration = data.get("duration")
    return SearchResult(
        id=video_id,
        title=str(data.get("title") or "Untitled"),
        url=f"{site}/watch?v={video_id}",
        thumbnail=pick_thumbnail(data) or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        channel=str(data.get("channel") or data.get("uploader") or ""),
        duration=float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else 0.0,
        views=int(views) if isinstance(views, int) and not isinstance(views, bool) else 0,
        live_status=str(data.get("live_status") or ""),
    )


def search(query: str, music: bool, limit: int, tools: ToolSet, cache_dir: Path,
           options: DownloadOptions | None = None, stop: threading.Event | None = None,
           on_result: Callable[[SearchResult], None] | None = None,
           runner: Runner = run_to_completion) -> list[SearchResult]:
    """Run a search, handing each result to `on_result` as it arrives (from the calling thread); raises
    AnalyzeError when the search can't be run and found nothing."""
    marker = run_marker()
    results: list[SearchResult] = []
    seen: set[str] = set()
    errors: list[str] = []

    def collect(stream: str, line: str) -> None:
        event = parse_line(stream, line, marker)
        if event.kind == "entry":
            result = result_from(event.data, music)
            if result is not None and result.id not in seen:
                seen.add(result.id)
                results.append(result)
                if on_result is not None:
                    on_result(result)
        elif event.kind == "error":
            errors.append(event.text)

    code, stopped = runner(search_command(query, music, limit, tools, cache_dir, options, marker), collect, stop)
    if stopped:
        raise AnalyzeError(classify("Cancelled"))
    if code != 0 and not results:
        raise AnalyzeError(classify(errors[-1] if errors else f"yt-dlp exited with status {code}"))
    return results
