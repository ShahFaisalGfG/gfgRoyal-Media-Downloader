"""Timed text: SRT, WebVTT, and LRC parsing, cue lookup, and LRC writing."""

from pathlib import Path

from gfgmd.core.captions import (
    Cue,
    clock,
    cue_at,
    is_synced_lrc,
    line_at,
    parse_file,
    parse_lrc,
    parse_timed_blocks,
    plain_text,
    sidecars,
    to_lrc,
)

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>Hello</i> there

2
00:00:04,000 --> 00:00:06,000
{\\an8}Second &amp; last
"""

VTT = """WEBVTT
Kind: captions
Language: en

NOTE a comment

00:00:01.000 --> 00:00:02.000 align:start position:0%
first<00:00:01.500><c> line</c>

00:00:02.000 --> 00:00:03.000 align:start position:0%
first line
second line
"""


def test_clock_reads_every_form() -> None:
    assert clock("1:02:03.5") == 3723.5
    assert clock("02:03,250") == 123.25
    assert clock("2:03.4") == 123.4


def test_srt_cues_lose_markup() -> None:
    assert parse_timed_blocks(SRT) == [Cue(1.0, 3.5, "Hello there"), Cue(4.0, 6.0, "Second & last")]


def test_vtt_rolling_captions_keep_only_new_lines() -> None:
    """YouTube's rolling captions repeat the last line; each cue keeps only what is new."""
    assert parse_timed_blocks(VTT) == [Cue(1.0, 2.0, "first line"), Cue(2.0, 3.0, "second line")]


def test_lrc_offsets_repeats_and_word_timings() -> None:
    text = "[ti:Song]\n[offset:+500]\n[00:01.00][00:09.00]Chorus <00:01.50>words\n[00:05.00]Verse\n\n"
    cues = parse_lrc(text)
    assert [(round(cue.start, 2), cue.text) for cue in cues] == [(0.5, "Chorus words"), (4.5, "Verse"),
                                                                  (8.5, "Chorus words")]
    assert cues[0].end == cues[1].start and cues[-1].end == cues[-1].start + 6.0
    assert is_synced_lrc(text) and not is_synced_lrc("Just words\nno times")


def test_cue_and_line_lookup() -> None:
    cues = [Cue(1.0, 2.0, "a"), Cue(5.0, 6.0, "b")]
    assert [cue_at(cues, t) for t in (0.5, 1.5, 3.0, 5.5, 7.0)] == [-1, 0, -1, 1, -1]
    assert [line_at(cues, t) for t in (0.5, 1.5, 3.0, 7.0)] == [-1, 0, 0, 1]
    assert cue_at([], 1.0) == -1


def test_lrc_round_trip_with_tags() -> None:
    cues = [Cue(0.0, 2.0, "One"), Cue(65.25, 70.0, "Two\nlines")]
    text = to_lrc(cues, title="Song [live]", artist="Band", length=200)
    assert text.splitlines()[:3] == ["[ti:Song (live)]", "[ar:Band]", "[length:03:20]"]
    assert "[01:05.25]Two / lines" in text
    assert [cue.text for cue in parse_lrc(text)] == ["One", "Two / lines"]
    assert plain_text(cues) == "One\nTwo\nlines"


def test_files_and_sidecars(tmp_path: Path) -> None:
    media = tmp_path / "Song (1080p).mp4"
    media.write_bytes(b"")
    (tmp_path / "Song (1080p).en.srt").write_text(SRT, encoding="utf-8")
    (tmp_path / "Song (1080p).lrc").write_text("[00:01.00]Hi", encoding="utf-8")
    (tmp_path / "Other.srt").write_text(SRT, encoding="utf-8")
    found = sidecars(media)
    assert [path.name for path in found] == ["Song (1080p).lrc", "Song (1080p).en.srt"]
    assert parse_file(found[1])[0].text == "Hello there"
    assert parse_file(tmp_path / "missing.srt") == []
