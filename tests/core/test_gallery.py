"""Saving pictures with gallery-dl: its command, the fake gallery-dl's runs, and merged results."""

from pathlib import Path

import pytest

from gfgmd.core.command import Auth
from gfgmd.core.errors import CATEGORIES, Failure
from gfgmd.core.gallery import (GalleryExecutor, GallerySpec, gallery_command, has_photos_pass, merge_results,
                                photos_only, pictures_follow, post_folder)
from gfgmd.core.jobs import JobResult
from gfgmd.core.options import DownloadOptions
from gfgmd.core.runner import run_to_completion
from gfgmd.core.sources import is_image_link, likely_media, source_from_url
from gfgmd.core.tools import ToolSet

TOOLS = ToolSet("yt-dlp", "ffmpeg", "ffprobe", "deno", gallery_dl="gallery-dl.exe")


def spec_for(url: str, root: Path, **changes) -> GallerySpec:
    return GallerySpec(url, source_from_url(url), root, root / ".job", **changes)


@pytest.fixture
def run_fake(fake_gallerydl):
    """A runner that hands gallery-dl's commands to the fake."""
    return lambda command, on_line, stop: run_to_completion(fake_gallerydl + command[1:], on_line, stop)


def test_the_command_ignores_configuration_and_names_every_choice(tmp_path):
    spec = spec_for("https://imgur.com/a/album1", tmp_path, auth=Auth(cookies_file="C:/run/cookies.txt"),
                    options=DownloadOptions(kind="photo", proxy="socks5://127.0.0.1:9050", limit_rate=500_000))
    command = gallery_command(spec, TOOLS, "@@m:")
    assert command[:3] == ["gallery-dl.exe", "--config-ignore", "--no-input"]
    assert command[command.index("-D") + 1] == str(tmp_path / "Imgur album1")
    assert command[command.index("--download-archive") + 1] == str(tmp_path / ".archives" / "imgur-photos.sqlite3")
    assert "after:@@m:saved {_path}" in command and "skip:@@m:skipped {_path}" in command
    assert command[command.index("-C") + 1] == "C:/run/cookies.txt"
    assert command[command.index("--proxy") + 1] == "socks5://127.0.0.1:9050"
    assert command[command.index("-r") + 1] == "500000"
    assert command[-2:] == ["--", "https://imgur.com/a/album1"] and "--filter" not in command
    cache = next(value for value in command if value.startswith("cache.file="))
    assert cache == f"cache.file={tmp_path / '.job' / 'gallery-dl-cache.sqlite3'}"


def test_a_posts_pictures_pass_leaves_its_videos_out(tmp_path):
    spec = spec_for("https://x.com/someone/status/1", tmp_path, images_only=True,
                    auth=Auth(browser="firefox"))
    command = gallery_command(spec, TOOLS, "@@m:")
    assert "extension.lower() in (" in command[command.index("--filter") + 1]
    assert "extractor.twitter.videos=false" in command  # gallery-dl calls X "twitter"
    assert command[command.index("--cookies-from-browser") + 1] == "firefox"


def test_which_links_save_pictures():
    imgur, post = source_from_url("https://imgur.com/a/album1"), source_from_url("https://x.com/a/status/1")
    assert photos_only(imgur, "https://imgur.com/a/album1") and not photos_only(post, "https://x.com/a/status/1")
    assert photos_only(source_from_url("https://site.test/p.JPG"), "https://site.test/p.JPG")
    assert is_image_link("https://site.test/a/b.webp?w=10") and not is_image_link("https://site.test/clip.mp4")
    assert likely_media("https://site.test/b.png")
    video, audio = DownloadOptions(kind="video"), DownloadOptions(kind="audio")
    assert has_photos_pass(post, video) and not has_photos_pass(post, audio)
    assert not has_photos_pass(post, video.with_changes(save_photos=False))
    youtube = source_from_url("https://www.youtube.com/watch?v=aaaaaaaaaaa")
    assert not has_photos_pass(youtube, video)
    # A profile's pictures could run to thousands; only posts get the pass.
    assert not has_photos_pass(source_from_url("https://x.com/someone"), video)


def test_post_folders_are_named_after_the_site_and_the_post():
    url = "https://www.instagram.com/p/DLtSAJ3t3Ia/?igsh=abc"
    assert post_folder(source_from_url(url), url) == "Instagram DLtSAJ3t3Ia"


def test_pictures_are_saved_and_reported(tmp_path, run_fake):
    seen = []
    spec = spec_for("https://imgur.com/a/album1", tmp_path, title="Album")
    result = GalleryExecutor(spec, lambda: TOOLS, on_file=lambda info, path: seen.append((info, path)),
                             runner=run_fake).run()
    assert result.state == "done" and result.message == "3 pictures saved"
    assert [path.name for path in result.files] == ["album 01.jpg", "album 02.png", "album 03.gif"]
    assert all(path.parent == tmp_path / "Imgur album1" for path in result.files)
    assert [info["_root"] for info, _ in seen] == [str(tmp_path)] * 3
    assert seen[0][0]["webpage_url"] == "https://imgur.com/a/album1"
    again = GalleryExecutor(spec, lambda: TOOLS, runner=run_fake).run()
    assert again.state == "done" and not again.files and again.message == "All 3 were downloaded before"


def test_a_single_picture_needs_no_folder(tmp_path, run_fake):
    (tmp_path / "only.jpg").write_bytes(b"taken")
    result = GalleryExecutor(spec_for("https://imgur.com/single", tmp_path), lambda: TOOLS, runner=run_fake).run()
    assert [path.name for path in result.files] == ["only (2).jpg"]  # under a free name
    assert not (tmp_path / "Imgur single").exists() and (tmp_path / "only.jpg").read_bytes() == b"taken"


def test_gallery_dl_exit_bits_name_the_failure(tmp_path, run_fake):
    auth = GalleryExecutor(spec_for("https://x.com/auth/status/1", tmp_path), lambda: TOOLS, runner=run_fake).run()
    assert auth.state == "needs_auth" and auth.failure is not None
    assert auth.failure.category.key == "auth_required" and "AuthRequired" in auth.failure.text
    unsupported = GalleryExecutor(spec_for("https://imgur.com/nothing", tmp_path), lambda: TOOLS,
                                  runner=run_fake).run()
    assert unsupported.state == "failed" and unsupported.failure is not None
    assert unsupported.failure.category.key == "unsupported"
    assert not (tmp_path / "Imgur nothing").exists()


def test_without_gallery_dl_the_tools_need_repairing(tmp_path):
    result = GalleryExecutor(spec_for("https://imgur.com/a/album1", tmp_path),
                             lambda: ToolSet("yt-dlp", "ffmpeg", "ffprobe", "deno")).run()
    assert result.state == "failed" and result.failure is not None
    assert result.failure.category.key == "gallery_missing" and result.failure.category.action == "repair_tools"


def test_stopping_ends_the_run(tmp_path):
    executor = GalleryExecutor(spec_for("https://imgur.com/a/album1", tmp_path), lambda: TOOLS,
                               runner=lambda command, on_line, stop: (1, stop.wait(5) or True))
    executor.stop()
    assert executor.run().state == "stopped"


def _failure(key: str) -> Failure:
    return Failure(CATEGORIES[key], "")


def test_a_posts_results_merge():
    video = Path("V/Clip (720p).mp4")
    pictures = [Path("P/a.jpg"), Path("P/b.jpg")]
    merged = merge_results(JobResult("done", 1, [video]), JobResult("done", 1, pictures, kind="photo"))
    assert merged.state == "done" and merged.files == [video, *pictures]
    assert merged.message == "1 video and 2 pictures saved"
    # Pictures only: yt-dlp found no video, so the pictures are the result.
    no_video = JobResult("failed", 1, failure=_failure("no_video"))
    assert pictures_follow(no_video)
    only = merge_results(no_video, JobResult("done", 1, pictures, kind="photo"))
    assert only.state == "done" and only.message == "2 pictures saved"
    # The pictures needing a sign-in keep the saved video, and say so.
    locked = JobResult("needs_auth", 1, kind="photo", failure=_failure("auth_required"))
    kept = merge_results(JobResult("done", 1, [video]), locked)
    assert kept.state == "done" and kept.files == [video]
    assert kept.message == "1 video saved; the pictures couldn't be saved: Sign in to this site to download this."
    # A video download that failed otherwise has no pictures pass.
    offline = JobResult("failed", 2, failure=_failure("network"))
    assert not pictures_follow(offline) and merge_results(offline, locked) is offline



def test_download_again_leaves_the_archive_out(tmp_path):
    spec = spec_for("https://imgur.com/a/album1", tmp_path,
                    options=DownloadOptions(kind="photo", ignore_archive=True))
    assert "--download-archive" not in gallery_command(spec, TOOLS, "@@m:")
