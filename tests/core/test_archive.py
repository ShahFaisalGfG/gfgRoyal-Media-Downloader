"""Archives: the original script names, tolerant reading, seeding, and the shared lock."""

import os
import stat
import sys
from pathlib import Path

import pytest

from gfgmd.core.archive import ArchiveLock, append_archive, archive_path, read_archive_ids
from gfgmd.core.command import RunPaths
from gfgmd.core.options import DownloadOptions
from gfgmd.core.sources import source_from_url


def test_archive_names_per_profile(tmp_path: Path) -> None:
    """Keep the original script's names for video and separate audio archives."""
    source = source_from_url("https://youtu.be/jNQXAC9IVRw")
    assert archive_path(tmp_path, source, DownloadOptions(max_height=720).profile).name == "single-videos-720p.txt"
    audio = DownloadOptions(kind="audio", audio_format="opus", audio_quality=160).profile
    assert archive_path(tmp_path, source, audio).name == "single-videos-audio-opus-160k.txt"
    lossless = DownloadOptions(kind="audio", audio_format="flac").profile
    assert archive_path(tmp_path, source, lossless).name == "single-videos-audio-flac.txt"


def test_read_ignores_a_cut_short_last_line(tmp_path: Path) -> None:
    """A crash mid-write leaves a partial line, which must not count as downloaded."""
    archive = tmp_path / "a.txt"
    archive.write_bytes(b"youtube aaaaaaaaaaa\nbroken\nyoutube bbbb")
    assert read_archive_ids(archive) == {"aaaaaaaaaaa"}
    assert read_archive_ids(tmp_path / "missing.txt") == set()


def test_append_adds_only_new_ids(tmp_path: Path) -> None:
    """Seed an archive (subscriptions that start from new uploads) without duplicates."""
    archive = tmp_path / "sub" / "a.txt"
    assert append_archive(archive, "Youtube", ["a", "b", "a"]) == 2
    assert append_archive(archive, "youtube", ["b", "c"]) == 1
    assert archive.read_text(encoding="utf-8") == "youtube a\nyoutube b\nyoutube c\n"


def test_lock_is_exclusive(tmp_path: Path) -> None:
    """A second holder waits until the first releases."""
    archive = tmp_path / "a.txt"
    first = ArchiveLock(archive, timeout=0.1)
    second = ArchiveLock(archive, timeout=0.3)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


@pytest.mark.skipif(sys.platform != "win32", reason="the hidden attribute is a Windows file attribute")
def test_the_working_folders_are_hidden(tmp_path: Path) -> None:
    """.archives and .incomplete stay out of sight in Explorer, as their dot hides them elsewhere."""
    paths = RunPaths(tmp_path, tmp_path / ".archives" / "single-videos-best.txt", tmp_path / "jobs" / "1", tmp_path)
    paths.prepare()
    for folder in (tmp_path / ".archives", tmp_path / ".incomplete", tmp_path / "jobs"):
        hidden = bool(os.stat(folder).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
        assert hidden == folder.name.startswith(".")
    paths.prepare()  # an already hidden folder stays as it is
    assert os.stat(tmp_path / ".archives").st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN
