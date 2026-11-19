"""Time-of-day limits, queue start, check intervals, live timing, and subscription planning."""

import random
from datetime import datetime

import pytest

from gfgmd.core.schedule import (
    in_window,
    limit_at,
    live_launch_time,
    next_check,
    next_queue_start,
    per_job_limit,
    stagger,
)
from gfgmd.core.sources import source_from_url
from gfgmd.core.subscriptions import check_urls, parse_takeout, sort_entries


@pytest.mark.parametrize(("hour", "inside"), [(8, False), (9, True), (17, True), (18, False)])
def test_day_window(hour: int, inside: bool) -> None:
    assert in_window(datetime(2026, 11, 19, hour, 0), "09:00", "18:00") is inside


@pytest.mark.parametrize(("hour", "inside"), [(22, True), (2, True), (7, False), (12, False)])
def test_window_across_midnight(hour: int, inside: bool) -> None:
    assert in_window(datetime(2026, 11, 19, hour, 0), "22:00", "07:00") is inside


def test_limit_takes_the_lowest_active_rule() -> None:
    windows = [{"start": "09:00", "end": "18:00", "limit_kib": 500}, {"start": "12:00", "end": "13:00", "limit_kib": 100}]
    assert limit_at(datetime(2026, 1, 1, 8), 0, windows) == 0
    assert limit_at(datetime(2026, 1, 1, 10), 0, windows) == 500
    assert limit_at(datetime(2026, 1, 1, 12, 30), 2000, windows) == 100
    assert limit_at(datetime(2026, 1, 1, 20), 2000, windows) == 2000


def test_per_job_limit_shares_the_total() -> None:
    assert per_job_limit(0, 3) == 0
    assert per_job_limit(1200, 3) == 400 * 1024
    assert per_job_limit(10, 4) == 16 * 1024  # never below a usable floor


def test_next_queue_start() -> None:
    assert next_queue_start(datetime(2026, 1, 1, 8), "09:30") == datetime(2026, 1, 1, 9, 30)
    assert next_queue_start(datetime(2026, 1, 1, 10), "09:30") == datetime(2026, 1, 2, 9, 30)


def test_next_check_jitter_stays_within_ten_percent() -> None:
    rng = random.Random(1)
    for _ in range(50):
        delay = next_check(0, 6, rng)
        assert 6 * 3600 * 0.9 <= delay <= 6 * 3600 * 1.1


def test_stagger_and_live_launch() -> None:
    assert stagger(3, 100) == [100, 110, 120]
    assert live_launch_time(10_000, 1_000) == 9_700
    assert live_launch_time(10_000, 9_900) == 9_900


def test_check_urls_cover_channel_tabs() -> None:
    channel = source_from_url("https://www.youtube.com/@x")
    assert check_urls(channel, "https://www.youtube.com/@x") == [
        "https://www.youtube.com/@x/videos", "https://www.youtube.com/@x/shorts", "https://www.youtube.com/@x/streams"]
    tab = source_from_url("https://www.youtube.com/@x/shorts")
    assert check_urls(tab, "https://www.youtube.com/@x/shorts") == ["https://www.youtube.com/@x/shorts"]


def test_sort_entries() -> None:
    entries = [
        {"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "c", "live_status": "is_upcoming"},
        {"id": "d", "availability": "subscriber_only"}, {"id": "e"}, {"title": "no id"},
    ]
    result = sort_entries(entries, archived={"b"}, seen={"e": "skipped"})
    assert [e["id"] for e in result.new] == ["a"]
    assert [e["id"] for e in result.upcoming] == ["c"]
    assert [e["id"] for e in result.unreachable] == ["d"]


def test_parse_takeout() -> None:
    text = ("﻿Channel Id,Channel Url,Channel Title\n"
            "UC1,http://www.youtube.com/channel/UC1,First\n"
            "UC2,https://www.youtube.com/channel/UC2,\"Second, with comma\"\n\n")
    assert parse_takeout(text) == [("https://www.youtube.com/channel/UC1", "First"),
                                   ("https://www.youtube.com/channel/UC2", "Second, with comma")]
    with pytest.raises(ValueError):
        parse_takeout("a,b\n1,2\n")
