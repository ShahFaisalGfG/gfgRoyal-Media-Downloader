"""The command-line tool: the original script's options, defaults, exit codes, and the new options."""

import argparse
import io
import json
import re
import shlex
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gfgmd import cli
from gfgmd.config.defaults import AppInfo
from gfgmd.core import naming
from gfgmd.core.errors import CATEGORIES
from gfgmd.core.jobs import JobResult, JobSpec
from gfgmd.core.progress import Event, Snapshot
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import source_from_url
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
    """Say how to get the tools and exit with status 2; --verbose names the missing programs."""
    from gfgmd.core.tools import ToolsMissing
    with patch.object(cli, "find_dependencies", side_effect=ToolsMissing(["yt-dlp", "deno"])):
        assert cli.run([URL, "--output-dir", str(tmp_path)]) == 2
        err = capsys.readouterr().err
        assert "Open the app once to install them" in err and "yt-dlp" not in err
        assert cli.run([URL, "--output-dir", str(tmp_path), "--verbose"]) == 2
    assert "yt-dlp, deno" in capsys.readouterr().err


def test_missing_cookies_file_exits_2(tmp_path: Path) -> None:
    """Refuse a cookies path that doesn't exist."""
    with patch.object(cli, "find_dependencies", return_value=TOOLS):
        assert cli.run([URL, "--output-dir", str(tmp_path), "--cookies", str(tmp_path / "nope.txt")]) == 2


def run_fake(fake_ytdlp: list[str], argv: list[str], tools: ToolSet = TOOLS) -> int:
    def runner(command, on_line, stop):
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)
    original = cli.JobExecutor

    def executor(*args, **kwargs):
        kwargs["runner"] = runner
        return original(*args, **kwargs)
    with (patch.object(cli, "find_dependencies", return_value=tools), patch.object(cli, "JobExecutor", executor),
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
    assert "Attempt 1 didn't finish. Trying again in 2 seconds." in capsys.readouterr().out


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


def test_app_controls_become_command_line_options(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """Where the app would say "choose another folder" or "wait for it", the command line names its option."""
    from gfgmd.core.errors import CATEGORIES, Failure
    for key, option in (("disk_full", "--output-dir"), ("folder_missing", "--output-dir"),
                        ("upcoming", "--wait-for-video"), ("auth_required", "--cookies")):
        cli._report(JobResult("failed", attempts=1, failure=Failure(CATEGORIES[key], "")), tmp_path, strict=False)
        assert option in capsys.readouterr().err


def test_broken_tools_report_how_to_reinstall(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A tool that didn't start reads as a reinstall step; its error text shows only with --verbose."""
    from gfgmd.core.errors import CATEGORIES, Failure
    result = JobResult("failed", attempts=1, failure=Failure(CATEGORIES["tools"], "yt-dlp didn't start: [WinError 2]"))
    assert cli._report(result, tmp_path, strict=False) == 2
    err = capsys.readouterr().err
    assert "Open the app once" in err and "WinError" not in err
    assert cli._report(result, tmp_path, strict=False, verbose=True) == 2
    assert "WinError 2" in capsys.readouterr().err


def test_progress_line_reads_plainly() -> None:
    """Song or video n of m, the stage, size, speed, and the time left in words."""
    snap = Snapshot(stage="Downloading", item_index=2, item_count=8, total=40 * 1024 * 1024, item_fraction=0.45,
                    speed=2.1 * 1024 * 1024, eta=75)
    expected = "Video 2 of 8  Downloading  45% of 40.0 MB  2.1 MB/s  about 1 minute left"
    assert cli._progress_line(snap, "video") == expected
    assert cli._progress_line(snap, "audio").startswith("Song 2 of 8  ")
    assert cli._progress_line(Snapshot(stage="Starting", item_count=8), "video") == "Starting"


def test_progress_line_skips_the_first_size_guess() -> None:
    """yt-dlp's opening guess from one small part ("100% of 1.0 KB") shows as what came so far."""
    snap = Snapshot(stage="Downloading", total=1024, downloaded=1024, item_fraction=1.0)
    assert cli._progress_line(snap, "video") == "Downloading  1.0 KB"


def test_a_link_typed_without_https_downloads(fake_ytdlp: list[str], tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    """"fake.test/ok" gets its https:// as in the app's link box; plain words are still refused."""
    assert run_fake(fake_ytdlp, ["fake.test/ok", "--output-dir", str(tmp_path)]) == 0
    assert "Downloading https://fake.test/ok" in capsys.readouterr().out
    assert run_fake(fake_ytdlp, ["not-a-link", "--output-dir", str(tmp_path)]) == 2
    assert "starts with https://" in capsys.readouterr().err


def test_the_closing_line_does_not_repeat_the_reason(fake_ytdlp: list[str], tmp_path: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    """A private video says why as it happens; the closing line then only says the download didn't finish."""
    assert run_fake(fake_ytdlp, ["https://fake.test/private", "--output-dir", str(tmp_path)]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].endswith(CATEGORIES["private"].message) and lines[-1] == "The download didn't finish."


def test_playlist_problems_name_the_video_without_tool_text(fake_ytdlp: list[str], tmp_path: Path,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    """A private video in a list reads as a plain sentence; the tool's own line shows only with --verbose."""
    assert run_fake(fake_ytdlp, ["https://fake.test/playlist", "--output-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    private = CATEGORIES["private"]
    assert f"Couldn't download one of the videos: {private.message}" in captured.err
    assert f"Skipped a video: {private.final}" in captured.err
    assert "[youtube]" not in captured.err and "bbbbbbbbbbb" not in captured.err
    assert "Finished: " in captured.out and f"The files are in {tmp_path}" in captured.out
    assert run_fake(fake_ytdlp, ["https://fake.test/playlist", "--output-dir", str(tmp_path / "again"), "-v"]) == 0
    assert "Details: [youtube] bbbbbbbbbbb: Private video" in capsys.readouterr().err


def test_problems_name_the_title_and_warnings_need_verbose(capsys: pytest.CaptureFixture[str]) -> None:
    """A known title names the video; warnings stay hidden unless asked for."""
    args = cli.parse_args([URL])
    spec = cli.JobSpec(URL, source_from_url(URL), cli.options_from_args(args), None, None)  # type: ignore[arg-type]
    reporter = cli._Reporter([], spec, verbose=False)
    reporter(Event("item", {"id": "abc12345678", "title": "Talk"}))
    reporter(Event("error", {"id": "abc12345678"}, "[youtube] abc12345678: Video unavailable"))
    reporter(Event("warning", {}, "[youtube] abc12345678: nsig extraction failed"))
    captured = capsys.readouterr()
    assert captured.out == "Downloading: Talk\n"
    assert captured.err == f'Couldn\'t download "Talk": {CATEGORIES["removed"].message}\n'


def test_titles_in_any_script_print_on_any_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """A title the console's code page can't show prints with "?" instead of crashing the run."""
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")
    monkeypatch.setattr(sys, "stdout", stdout)
    cli.console_safe()
    print("Saved: MET THE LOVE OF MY LIFE ＊caught on camera＊ (720p).mp4")
    stdout.flush()
    assert stdout.buffer.getvalue().endswith(b"?caught on camera? (720p).mp4\n")


def json_events(text: str) -> list[dict]:
    """Every stdout line as JSON (a line that isn't JSON fails the test)."""
    return [json.loads(line) for line in text.splitlines()]


def test_json_reports_events_and_ends_with_done(fake_ytdlp: list[str], tmp_path: Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    """With --json, stdout is only JSON: the start, each video, its file, a skipped one, and the closing done."""
    assert run_fake(fake_ytdlp, ["https://fake.test/playlist", "--output-dir", str(tmp_path), "--json"]) == 0
    captured = capsys.readouterr()
    events = json_events(captured.out)
    assert captured.err == ""
    assert events[0] == {"event": "start", "url": "https://fake.test/playlist", "kind": "video",
                         "output_dir": str(tmp_path.resolve())}
    kinds = [event["event"] for event in events]
    assert "item" in kinds and "error" in kinds and kinds[-1] == "done"
    files = [event for event in events if event["event"] == "file"]
    assert files and all(Path(event["path"]).is_file() for event in files)
    skipped = [event for event in events if event["event"] == "skipped"]
    assert skipped[0]["id"] == "bbbbbbbbbbb" and skipped[0]["reason"] == CATEGORIES["private"].final
    done = events[-1]
    assert done["ok"] is True and done["exit_code"] == 0 and done["state"] == "done"
    assert (done["saved"], done["skipped"], done["output_dir"]) == (len(files), 1, str(tmp_path.resolve()))


def test_json_failure_names_its_reason_and_status(fake_ytdlp: list[str], tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    """A failed download's done event carries the exit status, the reason, and its kind."""
    assert run_fake(fake_ytdlp, ["https://fake.test/private", "--output-dir", str(tmp_path), "--json"]) == 1
    done = json_events(capsys.readouterr().out)[-1]
    assert done["ok"] is False and done["exit_code"] == 1 and done["category"] == "private"
    assert done["message"].endswith(CATEGORIES["private"].final)


def test_json_progress_and_retries(fake_ytdlp: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A retry is an event of its own, and progress carries numbers rather than a sentence."""
    with patch.object(cli, "_PROGRESS_EVERY", 0.0):
        assert run_fake(fake_ytdlp, ["https://fake.test/flaky", "--output-dir", str(tmp_path), "--retry-delay", "2",
                                     "--json"]) == 0
    events = json_events(capsys.readouterr().out)
    assert {"event": "retry", "attempt": 1, "wait_seconds": 2} in events
    progress = next(event for event in events if event["event"] == "progress")
    assert {"fraction", "overall", "downloaded", "total", "speed", "eta", "stage"} <= set(progress)


def test_json_invalid_input_and_ctrl_c(capsys: pytest.CaptureFixture[str]) -> None:
    """A link that can't be used, and Ctrl+C, each end in one done event with their status."""
    assert cli.main(["ftp://example.com/x", "--json"]) == 2
    done = json_events(capsys.readouterr().out)
    assert len(done) == 1 and done[0]["event"] == "done" and done[0]["exit_code"] == 2 and "https://" in done[0]["message"]
    with patch.object(cli, "run", side_effect=KeyboardInterrupt):
        assert cli.main([URL, "--json"]) == 130
    done = json_events(capsys.readouterr().out)
    assert done == [{"event": "done", "ok": False, "exit_code": 130, "state": "stopped",
                     "message": "Stopped. Run the same command to resume later."}]


def test_the_skill_command_runs_before_a_link_is_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`gfgmd skill ...` installs and lists the skill; any other first word is still a link."""
    assert cli.main(["skill", "install", "--dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["installed"] == [str(tmp_path / "gfgmd")]
    assert (tmp_path / "gfgmd" / "SKILL.md").is_file()
    assert cli.main(["skill", "path", "--dir", str(tmp_path)]) == 0
    assert "(installed)" in capsys.readouterr().out


SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "gfgmd"


def skill_command_lines() -> list[list[str]]:
    """Every gfgmd command in the skill's code blocks, split as a shell would."""
    lines = []
    for doc in sorted(SKILL_DIR.rglob("*.md")):
        for block in re.findall(r"```powershell\n(.*?)```", doc.read_text(encoding="utf-8"), re.DOTALL):
            lines += [shlex.split(line, posix=False) for line in block.splitlines() if line.startswith("gfgmd ")]
    return [[part.strip('"') for part in line] for line in lines]


def test_every_command_in_the_skill_parses() -> None:
    """The skill can't drift from the tool: each command it shows is accepted by the real parser."""
    commands = skill_command_lines()
    assert len(commands) >= 15
    skill_parser = argparse.ArgumentParser(prog="gfgmd skill")
    cli.agent_skills.add_skill_commands(skill_parser, "gfgmd")
    for argv in commands:
        if argv[1] == "skill":
            skill_parser.parse_args(argv[2:])
        elif argv[1] == "search":
            cli.search_parser().parse_args(argv[2:])
        elif argv[1] not in ("URL",):
            cli.parse_args(argv[1:])


def test_the_skill_documents_every_option_and_no_others() -> None:
    """Each option of gfgmd is in the command reference, and every option the skill names exists."""
    reference = (SKILL_DIR / "references" / "commands.md").read_text(encoding="utf-8")
    options = {flag for parser in (cli.build_parser(), cli.search_parser()) for action in parser._actions
               for flag in action.option_strings if flag.startswith("--") and flag != "--help"}
    named = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", "".join(
        doc.read_text(encoding="utf-8") for doc in SKILL_DIR.rglob("*.md"))))
    skill_options = {"--agent", "--dir"}
    assert options <= set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", reference))
    assert named <= options | skill_options


def test_json_stays_exact_on_any_console(capsys: pytest.CaptureFixture[str]) -> None:
    """Non-ASCII titles and paths are escaped, so a console's code page can't turn them into "?"."""
    path = str(Path("C:/Music") / "\u0646\u0639\u062a \u2014 Live \uff0a.mp3")
    cli._Console(json_lines=True).saved({"id": "x", "title": "\u0646\u0639\u062a"}, Path(path))
    line = capsys.readouterr().out
    assert line.isascii() and json.loads(line)["path"] == path


class _Stopped(Exception):
    """Ends a run once its download would start."""


def _planned(argv: list[str], tmp_path: Path) -> JobSpec:
    """The download a command would run (nothing is downloaded)."""
    planned: list[JobSpec] = []

    class Executor:
        def __init__(self, spec: JobSpec, *args: object, **kwargs: object) -> None:
            planned.append(spec)

        def run(self, sleep: object) -> None:
            raise _Stopped

    with patch.object(cli, "find_dependencies", return_value=TOOLS), patch.object(cli, "JobExecutor", Executor):
        with pytest.raises(_Stopped):
            cli.run([*argv, "--output-dir", str(tmp_path), "--json"])
    return planned[0]


def test_a_video_inside_a_playlist_downloads_alone_unless_the_playlist_is_asked_for(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    link = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghijklmnop&index=3"
    spec = _planned([link], tmp_path)
    assert (spec.source.kind, spec.url) == ("video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    warning = [event for event in json_events(capsys.readouterr().out) if event["event"] == "warning"]
    assert "--whole-playlist" in warning[0]["message"]
    spec = _planned([link, "--whole-playlist"], tmp_path)
    assert (spec.source.kind, spec.source.source_id, spec.url) == ("playlist", "PLabcdefghijklmnop", link)
    assert not [event for event in json_events(capsys.readouterr().out) if event["event"] == "warning"]
    assert _planned([link, "--items", "1:3"], tmp_path).source.kind == "playlist"


def run_fakes(fake_ytdlp: list[str], fake_gallerydl: list[str], argv: list[str], tools: ToolSet = TOOLS) -> int:
    """cli.run with the fake yt-dlp and the fake gallery-dl in place of the real ones."""
    original = cli.GalleryExecutor

    def gallery(*args, **kwargs):
        kwargs["runner"] = lambda command, on_line, stop: run_to_completion(fake_gallerydl + command[1:], on_line, stop)
        return original(*args, **kwargs)
    with patch.object(cli, "GalleryExecutor", gallery):
        return run_fake(fake_ytdlp, argv, tools)


PICTURE_TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno", gallery_dl="FAKE-GALLERY-DL")


def test_a_picture_site_link_saves_its_pictures(fake_ytdlp: list[str], fake_gallerydl: list[str], tmp_path: Path,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    status = run_fakes(fake_ytdlp, fake_gallerydl, ["https://imgur.com/a/album1", "--output-dir", str(tmp_path)],
                       PICTURE_TOOLS)
    assert status == 0
    assert sorted(path.name for path in (tmp_path / "Imgur album1").iterdir()) == [
        "album 01.jpg", "album 02.png", "album 03.gif"]
    assert "Finished: 3 pictures saved." in capsys.readouterr().out


def test_a_post_saves_its_video_and_its_pictures(fake_ytdlp: list[str], fake_gallerydl: list[str], tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["https://x.com/mixed/status/1", "--output-dir", str(tmp_path)]
    assert run_fakes(fake_ytdlp, fake_gallerydl, argv, PICTURE_TOOLS) == 0
    assert "Finished: 1 video and 1 picture saved." in capsys.readouterr().out
    assert (tmp_path / "mixed 01.jpg").is_file() and (tmp_path / "Mixed Post (720p).mp4").is_file()
    # --no-photos: the video only (saved before now), and gallery-dl isn't run.
    gallery_argv = Path(fake_gallerydl[-1]) / "gallery-argv.json"
    gallery_argv.unlink()
    assert run_fakes(fake_ytdlp, fake_gallerydl, [*argv, "--no-photos"], PICTURE_TOOLS) == 0
    assert "Finished: Already downloaded." in capsys.readouterr().out and not gallery_argv.exists()


def test_a_posts_pictures_without_gallery_dl_leave_the_video_saved(
        fake_ytdlp: list[str], fake_gallerydl: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_fakes(fake_ytdlp, fake_gallerydl, ["https://x.com/mixed/status/1", "--output-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert "Saving pictures needs gallery-dl" in said and "update the download tools to get it" in said
    assert "Finished: 1 video saved." in captured.out


def test_a_spotify_album_downloads_as_songs(fake_ytdlp: list[str], tmp_path: Path,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    from tests.core.test_spotify import ALBUM_ID, album_page

    class Offline(cli.SpotifyExecutor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, page=lambda url: album_page("Song One", "Song Two"),
                             cover=lambda url: b"\xff\xd8\xff",
                             runner=lambda command, on_line, stop=None, env=None: run_to_completion(
                                 fake_ytdlp + command[1:], on_line, stop), **kwargs)
    with patch.object(cli, "SpotifyExecutor", Offline):
        assert run_fake(fake_ytdlp, [f"https://open.spotify.com/album/{ALBUM_ID}", "--output-dir", str(tmp_path)]) == 0
    assert "Finished: 2 songs saved." in capsys.readouterr().out
    assert sorted(path.name for path in (tmp_path / "Fake Album").iterdir()) == [
        "Fake Artist - Song One.mp4", "Fake Artist - Song Two.mp4"]
