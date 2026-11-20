"""The command-line tool: the original script's options, defaults, exit codes, and the new options."""

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd import cli
from gfgmd.config.defaults import AppInfo
from gfgmd.core import naming
from gfgmd.core.jobs import JobResult
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet

URL = "https://www.youtube.com/playlist?list=PLtest123"
TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


def test_version_flag_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Print the version and exit without needing a link."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_args(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"gfgmd {AppInfo.APP_VERSION}"


def test_main_returns_the_run_status() -> None:
    """Hand the downloader's exit status to the shell."""
    with patch.object(cli, "run", return_value=1):
        assert cli.main() == 1


def test_main_stops_on_ctrl_c(capsys: pytest.CaptureFixture[str]) -> None:
    """Stop with status 130 and explain how to resume."""
    with patch.object(cli, "run", side_effect=KeyboardInterrupt):
        assert cli.main() == 130
    assert "Run the same command to resume later." in capsys.readouterr().err


def test_version_1_defaults() -> None:
    """Keep the original script's resolution, fragments, retries, and download order."""
    args = cli.parse_args([URL])
    options = cli.options_from_args(args)
    assert (args.resolution, args.concurrent_fragments, args.max_attempts, args.retry_delay) == (1080, 8, 0, 10)
    assert (options.kind, options.container, options.codec_profile) == ("video", "mp4", "balanced")
    assert not (options.embed_thumbnail or options.embed_metadata or options.embed_chapters)


@pytest.mark.parametrize("count", ("0", "17", "many"))
def test_fragment_count_rejects_invalid_values(count: str) -> None:
    """Reject values outside the configured range before starting yt-dlp."""
    with pytest.raises(SystemExit) as exc:
        cli.parse_args([URL, "--concurrent-fragments", count])
    assert exc.value.code == 2


@pytest.mark.parametrize(("text", "expected"), [("500K", 512000), ("2M", 2097152), ("1.5MiB/s", 1572864), ("10", 10)])
def test_rate_limit(text: str, expected: int) -> None:
    """Read speeds in binary units."""
    assert cli.rate_limit(text) == expected


def test_new_options_map_to_download_options() -> None:
    """Turn audio, subtitle, embed, network, and selection flags into options."""
    args = cli.parse_args([URL, "--audio", "mp3", "--subs", "en,ur", "--embed-subs", "--embed", "--sponsorblock",
                           "mark", "--limit-rate", "1M", "--proxy", "http://127.0.0.1:8080", "--items", "1:3",
                           "-r", "0"])
    options = cli.options_from_args(args)
    assert (options.kind, options.audio_format, options.max_height) == ("audio", "mp3", 0)
    assert (options.subtitles, options.subtitle_langs) == ("embed", "en,ur")
    assert options.embed_thumbnail and options.sponsorblock == "mark"
    assert (options.limit_rate, options.proxy, options.items) == (1048576, "http://127.0.0.1:8080", "1:3")


def test_bad_proxy_is_rejected() -> None:
    """Refuse a proxy that isn't a URL."""
    with pytest.raises(SystemExit):
        cli.parse_args([URL, "--proxy", "not a proxy"])


def test_unusable_link_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """Report a link that can't be downloaded with status 2."""
    assert cli.run(["ftp://example.com/x"]) == 2
    assert "https://" in capsys.readouterr().err


def test_missing_tools_exit_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Name the missing programs and exit with status 2."""
    from gfgmd.core.tools import ToolsMissing
    with patch.object(cli, "find_dependencies", side_effect=ToolsMissing(["yt-dlp", "deno"])):
        assert cli.run([URL, "--output-dir", str(tmp_path)]) == 2
    assert "yt-dlp, deno" in capsys.readouterr().err


def test_missing_cookies_file_exits_2(tmp_path: Path) -> None:
    """Refuse a cookies path that doesn't exist."""
    with patch.object(cli, "find_dependencies", return_value=TOOLS):
        assert cli.run([URL, "--output-dir", str(tmp_path), "--cookies", str(tmp_path / "nope.txt")]) == 2


def run_fake(fake_ytdlp: list[str], argv: list[str]) -> int:
    def runner(command, on_line, stop):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    original = cli.JobExecutor

    def executor(*args, **kwargs):
        kwargs["runner"] = runner
        return original(*args, **kwargs)
    with (patch.object(cli, "find_dependencies", return_value=TOOLS), patch.object(cli, "JobExecutor", executor),
          patch.object(naming, "video_quality", return_value=720), patch.object(cli.time, "sleep")):
        return cli.run(argv)


def test_download_finishes_with_clean_name(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Save a single video straight into the download folder, with the measured quality in the name."""
    status = run_fake(fake_ytdlp, ["https://fake.test/ok", "--output-dir", str(tmp_path)])
    assert status == 0
    assert (tmp_path / "Clip (720p).mp4").exists()


def test_failed_attempt_retries_then_succeeds(fake_ytdlp: list[str], tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """Resume after a failed attempt without another command."""
    assert run_fake(fake_ytdlp, ["https://fake.test/flaky", "--output-dir", str(tmp_path), "--retry-delay", "2"]) == 0
    assert "Retrying in 2 seconds" in capsys.readouterr().out


def test_attempt_limit_returns_failure(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Report an incomplete download to a scheduler after the selected limit."""
    assert run_fake(fake_ytdlp, ["https://fake.test/flaky", "--output-dir", str(tmp_path), "--max-attempts", "1"]) == 1


def test_strict_fails_on_skipped_items(fake_ytdlp: list[str], tmp_path: Path) -> None:
    """Skipped items pass by default and fail with --strict."""
    assert run_fake(fake_ytdlp, ["https://fake.test/playlist", "--output-dir", str(tmp_path)]) == 0
    other = tmp_path / "again"
    assert run_fake(fake_ytdlp, ["https://fake.test/playlist", "--output-dir", str(other), "--strict"]) == 1


def test_report_messages(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Explain sign-in failures with the cookie options."""
    from gfgmd.core.errors import classify
    result = JobResult("needs_auth", attempts=1, failure=classify("Sign in to confirm your age"))
    assert cli._report(result, tmp_path, strict=False) == 1
    assert "--cookies" in capsys.readouterr().err


def test_titles_in_any_script_print_on_any_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """A title the console's code page can't show prints with "?" instead of crashing the run."""
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", stdout)
    cli.console_safe()
    print("Saved: MET THE LOVE OF MY LIFE ＊caught on camera＊ (720p).mp4")
    stdout.flush()
    assert stdout.buffer.getvalue().endswith(b"?caught on camera? (720p).mp4\n")
