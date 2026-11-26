"""Every command this app builds is accepted by the yt-dlp installed on this machine.

Each command runs without its link, so yt-dlp parses every option and then stops with "You must
provide at least one URL" before touching the network. Any other error means a flag or value this
yt-dlp doesn't accept. Skipped when the programs aren't installed (CI on a bare runner).
"""

import subprocess
from pathlib import Path

import pytest

from gfgmd.core.command import RunPaths, analyze_command, check_command, download_command, list_command
from gfgmd.core.options import DownloadOptions
from gfgmd.core.platform import hidden_window_flags
from gfgmd.core.sources import source_from_url
from gfgmd.core.tools import ToolsMissing, resolve_tools

try:
    TOOLS = resolve_tools("path")
except ToolsMissing:
    TOOLS = None

pytestmark = pytest.mark.skipif(TOOLS is None, reason="yt-dlp, ffmpeg, ffprobe, or deno is not installed")

VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
OPTION_SETS = {
    "default": DownloadOptions(),
    "audio": DownloadOptions(kind="audio", audio_format="mp3", embed_thumbnail=True, embed_metadata=True),
    "everything": DownloadOptions(
        container="mkv", codec_profile="best", subtitles="embed", auto_subtitles=True, embed_thumbnail=True,
        embed_metadata=True, embed_chapters=True, sponsorblock="remove", filename_style="date-title",
        limit_rate=500_000, proxy="socks5://127.0.0.1:9050", force_ipv4=True, items="1:5,8",
        live_from_start=True, wait_for_video=True),
    "webm": DownloadOptions(container="webm", subtitles="sidecar", filename_style="index-title", sponsorblock="mark"),
    "audio-lyrics": DownloadOptions(kind="audio", audio_format="opus", audio_quality=160, auto_subtitles=True,
                                    embed_thumbnail=True, embed_metadata=True, subtitle_langs="en.*,ur"),
    "audio-wav": DownloadOptions(kind="audio", audio_format="wav", embed_thumbnail=True, cover="original"),
    "audio-original": DownloadOptions(kind="audio", audio_format="best", lyrics=False),
    "multi-audio": DownloadOptions(container="mp4", audio_tracks="languages", audio_langs=("es", "pt-BR"),
                                   subtitles="both", subtitle_format="vtt", embed_thumbnail=True),
}


def assert_accepted(command: list[str]) -> None:
    argv = command[:command.index("--")] if "--" in command else command
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                            creationflags=hidden_window_flags())
    errors = [line for line in result.stderr.splitlines() if line.startswith("ERROR:") or ": error: " in line]
    assert len(errors) == 1 and errors[0].endswith("error: You must provide at least one URL."), result.stderr


@pytest.mark.parametrize("name", sorted(OPTION_SETS))
def test_download_commands_parse(name: str, tmp_path: Path) -> None:
    assert TOOLS is not None
    paths = RunPaths(tmp_path, tmp_path / ".archives" / "a.txt", tmp_path / "job", tmp_path / "cache")
    command = download_command(VIDEO, source_from_url(VIDEO), OPTION_SETS[name].validate(), TOOLS, paths,
                               skip_ids=["aaaaaaaaaaa"])
    assert_accepted(command)


def test_facebook_command_parses(tmp_path: Path) -> None:
    assert TOOLS is not None
    url = "https://www.facebook.com/reel/1195289147628387"
    paths = RunPaths(tmp_path, tmp_path / ".archives" / "a.txt", tmp_path / "job", tmp_path / "cache")
    assert_accepted(download_command(url, source_from_url(url), DownloadOptions(kind="audio").validate(), TOOLS, paths))


def test_analyze_and_check_commands_parse(tmp_path: Path) -> None:
    assert TOOLS is not None
    assert_accepted(analyze_command(VIDEO, TOOLS, tmp_path, options=OPTION_SETS["everything"]))
    assert_accepted(list_command(VIDEO, TOOLS, tmp_path, options=OPTION_SETS["everything"]))
    command, _ = check_command([VIDEO], TOOLS, tmp_path / "a.txt", tmp_path, tmp_path)
    assert_accepted(command)
