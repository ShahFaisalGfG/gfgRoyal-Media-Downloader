"""Error categories and the retry, skip, and stop verdicts."""

import pytest

from gfgmd.core.errors import CATEGORIES, Failure, Policy, classify, folder_failure, given_up, judge


@pytest.mark.parametrize(("message", "key"), [
    ("[youtube] abc: Private video. Sign in if you've been granted access to this video", "private"),
    ("[youtube] abc: Video unavailable. This video has been removed by the uploader", "removed"),
    ("[youtube] abc: Sign in to confirm your age. This video may be inappropriate", "auth_required"),
    ("[youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser", "bot_check"),
    ("[youtube] abc: The provided YouTube account cookies are no longer valid", "cookies_stale"),
    ("[youtube] abc: This video is available to this channel's members on level: Tier", "auth_required"),
    ("[youtube] abc: The uploader has not made this video available in your country", "geo"),
    ("[generic] abc: This video is DRM protected", "drm"),
    ("[youtube] abc: Requested format is not available. Use --list-formats", "format"),
    ("Unsupported URL: https://example.com/", "unsupported"),
    ("unable to download video data: HTTP Error 429: Too Many Requests", "rate_limited"),
    ("unable to download video data: HTTP Error 403: Forbidden", "bot_check"),
    ("unable to write data: [Errno 28] No space left on device", "disk_full"),
    ("[WinError 5] Access is denied: 'C:\\Videos\\x.part'", "access_denied"),
    ("[WinError 32] The process cannot access the file because it is being used by another process", "file_locked"),
    ("[youtube] abc: Unable to extract initial player response; please report this issue", "extractor_broken"),
    ("Postprocessing: Conversion failed!", "postprocess"),
    ("[youtube] abc: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>", "network"),
    ("[youtube] abc: This live event will begin in 3 hours.", "upcoming"),
    ("ffmpeg not found. Please install or provide the path", "tools"),
    ("something nobody has seen before", "unknown"),
    ("[dailymotion] x5kesuj: No video formats found!; please report this issue on https://github.com", "no_formats"),
    ("[youtube:tab] @jawed: This channel does not have a shorts tab", "empty_tab"),
    ("[youtube] jfKfPfyJRdk: This live stream recording is not available.", "removed"),
])
def test_classify(message: str, key: str) -> None:
    """Map real yt-dlp messages to their categories."""
    assert classify(message).category.key == key


def test_judge_prefers_the_most_severe() -> None:
    """A full disk outranks a sign-in request, which outranks a network error and skips."""
    failures = [classify("Private video", "a"), classify("getaddrinfo failed"), classify("No space left on device")]
    assert judge(failures).policy is Policy.PAUSE_QUEUE
    assert judge(failures[:2]).policy is Policy.RETRY
    assert judge([classify("Sign in to confirm your age"), failures[1]]).policy is Policy.STOP


def test_judge_lists_skipped_items() -> None:
    """Report permanently failing items so later attempts leave them out."""
    verdict = judge([classify("Private video", "a"), classify("has been removed", "b"), classify("Private video", "a")])
    assert verdict.policy is Policy.SKIP
    assert verdict.skipped_ids == ("a", "b")
    assert verdict.headline is not None and verdict.headline.item_id == "a"


@pytest.mark.parametrize(
    ("message", "signed_in", "single", "key"),
    [
        ("ERROR: [youtube:tab] PLx: YouTube said: The playlist does not exist.", False, False, "private_signin"),
        ("ERROR: [youtube:tab] PLx: YouTube said: The playlist does not exist.", True, False, "removed"),
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", False, True, "private_signin"),
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", False, False, "private"),
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", True, True, "private"),
        ("ERROR: [Instagram] Cabc: There is no video in this post", False, True, "no_video"),
        ("ERROR: [twitter] 123: No video could be found in this tweet", True, True, "no_video"),
    ],
)
def test_private_content_asks_for_a_sign_in_when_signed_out(message: str, signed_in: bool, single: bool,
                                                             key: str) -> None:
    """A private playlist or video may be the user's own: signed out, ask to sign in instead of skipping.

    A private video inside someone else's public playlist is still skipped.
    """
    failure = classify(message, signed_in=signed_in, single=single)
    assert failure.category.key == key
    if key == "private_signin":
        assert failure.category.policy is Policy.STOP and failure.category.action == "signin"


def test_cut_connections_are_network_trouble_not_a_broken_yt_dlp() -> None:
    """TikTok cut off by the network reads like a yt-dlp bug; it is retried, not "update yt-dlp"."""
    message = ("ERROR: [TikTok] 6748451240264420610: Unable to download webpage: Failed to perform, curl: (35) "
               "BoringSSL SSL_connect: Connection closed abruptly; please report this issue on GitHub")
    assert classify(message).category.key == "network"
    assert classify("ERROR: [facebook] 1: Unable to download webpage: Read timed out.").category.key == "network"


def test_a_folder_that_cant_be_written_says_why() -> None:
    """Full, not allowed, or not there (an unplugged drive): each offers Choose folder."""
    full = folder_failure(OSError(28, "No space left on device"))
    denied = folder_failure(PermissionError(13, "Access is denied"))
    missing = folder_failure(FileNotFoundError(3, "The system cannot find the path specified"))
    assert [f.category.key for f in (full, denied, missing)] == ["disk_full", "access_denied", "folder_missing"]
    assert all(f.category.action == "choose_folder" for f in (full, denied, missing))


def test_a_video_given_up_on_is_skipped() -> None:
    """A temporary failure turned into a skip keeps its words; the attempt then ends like a skip."""
    failure = Failure(CATEGORIES["network"], "HTTP Error 403", "bbbbbbbbbbb")
    skipped = given_up(failure)
    assert skipped.category.policy is Policy.SKIP and skipped.category.final == CATEGORIES["network"].final
    assert judge([skipped]).policy is Policy.SKIP and judge([skipped]).skipped_ids == ("bbbbbbbbbbb",)
