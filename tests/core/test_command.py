"""The yt-dlp command lines: the original script's download rules plus the hardening and new options."""

import re
from pathlib import Path

import pytest

from gfgmd.core.command import (
    SQUARE_COVER,
    Auth,
    RunPaths,
    analyze_command,
    check_command,
    download_command,
    escape_template,
    format_selector,
    print_arg,
)
from gfgmd.core.options import DownloadOptions
from gfgmd.core.sources import source_from_url
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("yt-dlp.exe", r"C:\ff\bin\ffmpeg.exe", r"C:\ff\bin\ffprobe.exe", r"C:\deno\deno.exe")
URL = "https://www.youtube.com/playlist?list=PLtest123"
VIDEO_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
SHORT_URL = "https://www.youtube.com/shorts/jNQXAC9IVRw"


def paths(root: Path) -> RunPaths:
    return RunPaths(root, root / ".archives" / "key-1080p.txt", root / ".gfgmd" / "jobs" / "j", root / "cache")


def value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def values(command: list[str], flag: str) -> list[str]:
    return [command[i + 1] for i, arg in enumerate(command[:-1]) if arg == flag]


def test_download_is_resumable_mp4_like_version_1(tmp_path: Path) -> None:
    """Keep the original script's format rules, resume flags, archive, and folder names."""
    command = download_command(URL, source_from_url(URL), DownloadOptions(), TOOLS, paths(tmp_path))

    assert value(command, "--format") == (
        "bv[width<=1080][aspect_ratio<1]+ba/b[width<=1080][aspect_ratio<1]/"
        "bv[height<=1080]+ba/b[height<=1080]/bv[height<=?1080]+ba/b[height<=?1080]"
    )
    assert value(command, "--format-sort") == "lang,res,proto:m3u8,vcodec:h264,acodec:aac"
    assert value(command, "--merge-output-format") == "mp4"
    assert value(command, "--remux-video") == "mp4"
    assert value(command, "--http-chunk-size") == "8M"
    assert value(command, "--concurrent-fragments") == "8"
    assert "--throttled-rate" not in command
    assert value(command, "--download-archive") == str(tmp_path / ".archives" / "key-1080p.txt")
    assert values(command, "--paths") == [str(tmp_path), f"temp:{tmp_path / '.incomplete'}"]
    assert value(command, "--output") == "%(playlist).100B/%(title).100B [%(id).64B] (requested-1080p).%(ext)s"
    for flag in ("--continue", "--part", "--no-overwrites", "--abort-on-unavailable-fragments",
                 "--no-abort-on-error", "--yes-playlist"):
        assert flag in command
    assert "--no-playlist" not in command
    assert command[-2:] == ["--", URL]


def test_every_command_is_hardened(tmp_path: Path) -> None:
    """Load no config, plugins, or remote code, name tools by path, and end options before links."""
    source = source_from_url(VIDEO_URL)
    commands = [
        download_command(VIDEO_URL, source, DownloadOptions(), TOOLS, paths(tmp_path)),
        analyze_command(VIDEO_URL, TOOLS, tmp_path),
        check_command([VIDEO_URL], TOOLS, tmp_path / "a.txt", tmp_path, tmp_path)[0],
    ]
    for command in commands:
        assert command[0] == "yt-dlp.exe"
        for flag in ("--ignore-config", "--no-plugin-dirs", "--no-remote-components", "--no-js-runtimes",
                     "--windows-filenames"):
            assert flag in command
        assert value(command, "--js-runtimes") == r"deno:C:\deno\deno.exe"
        assert value(command, "--ffmpeg-location") == r"C:\ff\bin"
        assert "--no-config-locations" not in command
        assert "-U" not in command and "--update" not in command and "--exec" not in command
        assert command[command.index("--") + 1] == VIDEO_URL


@pytest.mark.parametrize(("url", "folder", "playlist_flag"), [
    (VIDEO_URL, "Single Videos", "--no-playlist"),
    (SHORT_URL, "Shorts", "--no-playlist"),
    ("https://www.youtube.com/@Some/shorts", "%(channel,uploader,playlist_uploader|Channel).100B/Shorts",
     "--yes-playlist"),
    ("https://vimeo.com/1", "%(extractor_key|Site).60B/%(playlist_title,playlist|Single Videos).100B",
     "--yes-playlist"),
])
def test_folders_by_link_type(url: str, folder: str, playlist_flag: str, tmp_path: Path) -> None:
    """Put each kind of link in its own folder."""
    options = DownloadOptions(max_height=720, fragments=4)
    command = download_command(url, source_from_url(url), options, TOOLS, paths(tmp_path))
    assert value(command, "--output") == f"{folder}/%(title).100B [%(id).64B] (requested-720p).%(ext)s"
    assert value(command, "--concurrent-fragments") == "4"
    assert playlist_flag in command


def test_audio_download(tmp_path: Path) -> None:
    """MP3 at 320 kbps by default, with a square cover, the artist cleaned up, and lyrics as LRC."""
    options = DownloadOptions(kind="audio", embed_thumbnail=True, embed_metadata=True)
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), options, TOOLS, paths(tmp_path))
    assert value(command, "--format") == "ba[acodec^=mp3]/ba/b"
    assert value(command, "--format-sort") == "lang,abr,asr"
    assert value(command, "--audio-format") == "mp3"
    assert value(command, "--audio-quality") == "320K"
    assert "--extract-audio" in command and "--embed-thumbnail" in command and "--embed-metadata" in command
    assert value(command, "--postprocessor-args") == SQUARE_COVER
    assert value(command, "--replace-in-metadata") == "uploader"
    assert value(command, "--convert-subs") == "lrc" and value(command, "--sub-langs") == "en.*"
    assert "--write-auto-subs" not in command
    assert "--merge-output-format" not in command
    assert "(requested-audio-mp3-320k)" in value(command, "--output")


@pytest.mark.parametrize("audio_format", ["flac", "wav", "best"])
def test_lossless_audio_has_no_bitrate(tmp_path: Path, audio_format: str) -> None:
    """FLAC, WAV, and the original stream ignore the bitrate; WAV gets its cover as a separate file."""
    options = DownloadOptions(kind="audio", audio_format=audio_format, embed_thumbnail=True, cover="original")
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), options, TOOLS, paths(tmp_path))
    assert "--audio-quality" not in command and "--postprocessor-args" not in command
    assert ("--write-thumbnail" in command) == (audio_format == "wav")
    assert ("--embed-thumbnail" in command) == (audio_format != "wav")
    assert f"(requested-audio-{audio_format})" in value(command, "--output")


def test_lyrics_off_and_cut_segments_skip_captions(tmp_path: Path) -> None:
    """No captions without lyrics, nor when SponsorBlock cuts parts out (their timings would drift)."""
    source = source_from_url(VIDEO_URL)
    off = download_command(VIDEO_URL, source, DownloadOptions(kind="audio", lyrics=False), TOOLS, paths(tmp_path))
    cut = download_command(VIDEO_URL, source, DownloadOptions(kind="audio", sponsorblock="remove"), TOOLS,
                           paths(tmp_path))
    assert "--write-subs" not in off and "--write-subs" not in cut
    assert "--sponsorblock-remove" in cut


def test_video_keeps_dubbed_audio_tracks(tmp_path: Path) -> None:
    """Chosen languages join the original track; a video without them falls back to the original."""
    options = DownloadOptions(container="mkv", audio_tracks="languages", audio_langs=("es", "pt-BR"))
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), options, TOOLS, paths(tmp_path))
    selector = value(command, "--format")
    assert selector.startswith("bv[width<=1080][aspect_ratio<1]+ba+ba[language^=es]+ba[language^=pt-BR]/"
                               "bv[width<=1080][aspect_ratio<1]+ba/")
    assert "--audio-multistreams" in command
    assert "--embed-metadata" in command  # it labels each track with its language
    single = download_command(VIDEO_URL, source_from_url(VIDEO_URL), DownloadOptions(), TOOLS, paths(tmp_path))
    assert "--audio-multistreams" not in single and "language^=" not in value(single, "--format")


def test_multiple_audio_tracks_need_mp4_or_mkv() -> None:
    """WebM can't take several tracks here, and the extra languages must be real codes."""
    with pytest.raises(ValueError, match="MP4 or MKV"):
        DownloadOptions(container="webm", audio_tracks="all", audio_langs=("es",)).validate()
    with pytest.raises(ValueError, match="more audio language"):
        DownloadOptions(audio_tracks="languages").validate()
    with pytest.raises(ValueError, match="look like"):
        DownloadOptions(audio_tracks="languages", audio_langs=("es; rm",)).validate()
    assert DownloadOptions(kind="audio", audio_tracks="languages").validate().multi_audio is False


@pytest.mark.parametrize(("mode", "expected", "absent"), [
    ("sidecar", ["--convert-subs"], ["--embed-subs"]),
    ("embed", ["--embed-subs", "--compat-options"], ["--convert-subs"]),
    ("both", ["--embed-subs", "--convert-subs"], ["--compat-options"]),
])
def test_subtitle_modes(tmp_path: Path, mode: str, expected: list[str], absent: list[str]) -> None:
    """Separate files, embedded tracks, or both; separate files in the chosen format."""
    options = DownloadOptions(subtitles=mode, subtitle_format="vtt")
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), options, TOOLS, paths(tmp_path))
    assert all(flag in command for flag in expected) and not any(flag in command for flag in absent)
    if "--convert-subs" in expected:
        assert value(command, "--convert-subs") == "vtt"


def test_every_option_reaches_yt_dlp(tmp_path: Path) -> None:
    """Pass subtitles, embeds, SponsorBlock, network, selection, live, and skip filters through."""
    options = DownloadOptions(
        container="mkv", codec_profile="best", subtitles="embed", subtitle_langs="en.*,ur", auto_subtitles=True,
        embed_thumbnail=True, embed_metadata=True, embed_chapters=True, sponsorblock="remove",
        sponsorblock_categories=("sponsor", "intro"), filename_style="index-title", limit_rate=500_000,
        proxy="socks5://127.0.0.1:9050", force_ipv4=True, items="1:5,8", live_from_start=True, wait_for_video=True,
    ).validate()
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), options, TOOLS, paths(tmp_path),
                               Auth(cookies_file=r"C:\run\cookies.txt"), skip_ids=["bbbbbbbbbbb", "bad id!"])
    assert value(command, "--format-sort") == "lang,res,fps,hdr:12"
    assert value(command, "--merge-output-format") == "mkv"
    assert value(command, "--sub-langs") == "en.*,ur"
    assert "--write-subs" in command and "--write-auto-subs" in command and "--embed-subs" in command
    assert value(command, "--compat-options") == "no-keep-subs"
    assert value(command, "--sponsorblock-remove") == "sponsor,intro"
    assert value(command, "--limit-rate") == "500000"
    assert value(command, "--proxy") == "socks5://127.0.0.1:9050"
    assert "--force-ipv4" in command
    assert value(command, "--playlist-items") == "1:5,8"
    assert "--live-from-start" in command and value(command, "--wait-for-video") == "15-120"
    assert value(command, "--cookies") == r"C:\run\cookies.txt"
    assert value(command, "--match-filters") == "id!=bbbbbbbbbbb"
    assert value(command, "--output").startswith("%(channel") is False
    assert "%(playlist_index&{:03d} - |)s%(title)" in value(command, "--output")


def test_sponsorblock_only_for_youtube_and_webm_has_no_thumbnail(tmp_path: Path) -> None:
    """Skip SponsorBlock on other sites and thumbnail embedding where WebM can't hold one."""
    options = DownloadOptions(container="webm", embed_thumbnail=True, sponsorblock="mark", subtitles="sidecar")
    command = download_command("https://vimeo.com/1", source_from_url("https://vimeo.com/1"), options, TOOLS,
                               paths(tmp_path))
    assert "--sponsorblock-mark" not in command
    assert "--embed-thumbnail" not in command
    assert value(command, "--merge-output-format") == "webm/mkv"
    assert value(command, "--format-sort") == "lang,res,vcodec:vp9,acodec:opus"
    assert value(command, "--convert-subs") == "srt"


def test_structured_output_and_journal(tmp_path: Path) -> None:
    """Ask for JSON progress, item, and file lines, and a journal yt-dlp writes itself."""
    weird = tmp_path / "100% done"
    run = RunPaths(weird, weird / "a.txt", weird / "job", weird / "cache")
    command = download_command(VIDEO_URL, source_from_url(VIDEO_URL), DownloadOptions(), TOOLS, run)
    templates = values(command, "--progress-template")
    assert templates[0].startswith("download:@@gfgr:dl {") and templates[1].startswith("postprocess:@@gfgr:pp {")
    prints = values(command, "--print")
    assert [p.split(":", 1)[0] for p in prints] == ["video", "video", "after_move"]
    index = command.index("--print-to-file")
    assert command[index + 2] == str(weird / "job" / "files.jsonl").replace("%", "%%")
    assert "--no-quiet" in command and "--progress" in command and "--no-simulate" in command


def test_print_rejects_unknown_stage() -> None:
    """Refuse a mistyped --print stage, which yt-dlp would print as text."""
    with pytest.raises(ValueError):
        print_arg("aftre_move", "%(id)s")


def test_best_quality_has_no_height_limit() -> None:
    """Take the best streams when the limit is 0."""
    assert format_selector(DownloadOptions(max_height=0)) == "bv*+ba/b"


def test_subscription_check_and_batch_file(tmp_path: Path) -> None:
    """Stop at the first archived upload, and move long link lists into a batch file."""
    urls = [f"https://www.youtube.com/@c{i}/videos" for i in range(60)]
    command, batch = check_command(urls, TOOLS, tmp_path / "a.txt", tmp_path, tmp_path, newest=30)
    for flag in ("--flat-playlist", "--lazy-playlist", "--break-on-existing", "--break-per-input"):
        assert flag in command
    assert value(command, "--playlist-items") == "1:30"
    assert value(command, "--batch-file") == str(tmp_path / "urls.txt")
    assert "--" not in command
    assert batch.splitlines() == urls


def test_escape_template() -> None:
    """Double every percent sign in a literal."""
    assert escape_template("50% off") == "50%% off"


def test_facebook_titles_lose_their_counts(tmp_path: Path) -> None:
    """A reel's "9.9K views · 340 reactions | " prefix is dropped from its title (and file name)."""
    url = "https://www.facebook.com/reel/1195289147628387"
    command = download_command(url, source_from_url(url), DownloadOptions(), TOOLS, paths(tmp_path))
    index = command.index("--replace-in-metadata")
    pattern = command[index + 2]
    assert command[index + 1] == "title" and command[index + 3] == ""
    assert re.sub(pattern, "", "9.9K views · 340 reactions | Caption here") == "Caption here"
    assert re.sub(pattern, "", "1,204 plays | Clip") == "Clip"
    youtube = download_command(VIDEO_URL, source_from_url(VIDEO_URL), DownloadOptions(), TOOLS, paths(tmp_path))
    assert "--replace-in-metadata" not in youtube
