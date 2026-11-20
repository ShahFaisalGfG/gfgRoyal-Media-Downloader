"""Sizes, lengths, and media nouns in plain words."""

import pytest

from gfgmd.utils.format import about_time, count_media, format_bytes, format_duration, format_time_left, format_wait, media_noun


def test_sizes_and_durations() -> None:
    assert format_bytes(1536) == "1.5 KB" and format_bytes(12) == "12 B"
    assert format_duration(75) == "1:15" and format_duration(3725) == "1:02:05"


def test_songs_and_videos_are_named_by_kind() -> None:
    assert media_noun("audio") == "song" and media_noun("video", 2) == "videos" and media_noun("live") == "video"
    assert count_media(1, "audio") == "1 song" and count_media(8, "video") == "8 videos"


@pytest.mark.parametrize(("seconds", "words"), [
    (3, "a few seconds"), (42, "about 40 seconds"), (75, "about 1 minute"), (200, "about 3 minutes"),
    (3590, "about 1 hour"), (4800, "about 1 hour 20 minutes"), (7200, "about 2 hours"),
    (40_000, "about 11 hours"),
])
def test_rough_lengths_in_words(seconds: float, words: str) -> None:
    assert about_time(seconds) == words


def test_time_left_and_waits() -> None:
    assert format_time_left(200) == "about 3 minutes left"
    assert format_wait(20) == "in 20 seconds" and format_wait(1) == "in 1 second"
    assert format_wait(130) == "in 2 minutes" and format_wait(5400) == "in about 1 hour 30 minutes"
