"""Sort yt-dlp's error messages into categories that decide whether to retry, skip, or ask the user."""

from __future__ import annotations

import errno
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class Policy(Enum):
    """What a failure means for the job."""

    RETRY = "retry"  # temporary: wait and try again
    SKIP = "skip"  # this item can never download as things stand; record it and move on
    STOP = "stop"  # the whole job needs the user (sign in, free space, repair tools)
    PAUSE_QUEUE = "pause_queue"  # nothing else can succeed either (the disk is full)
    UPDATE = "update"  # yt-dlp is probably out of date: update it, then retry once


@dataclass(frozen=True)
class Category:
    """One kind of failure and what the app does about it.

    `message` is what the user reads while the app handles it (for a temporary failure, while it
    waits to try again); `final_message`, when given, replaces it once the app has given up.
    """

    key: str
    policy: Policy
    message: str
    action: str = ""  # the button the UI offers: signin, update_tools, choose_folder, repair_tools
    final_message: str = ""

    @property
    def final(self) -> str:
        """What the user reads once nothing more will be tried."""
        return self.final_message or self.message


@dataclass(frozen=True)
class Failure:
    """One classified error line."""

    category: Category
    text: str
    item_id: str = ""


CATEGORIES = {category.key: category for category in (
    Category("auth_required", Policy.STOP, "Sign in to this site to download this.", "signin"),
    Category("cookies_stale", Policy.STOP, "Your sign-in to this site has expired. Sign in again.", "signin"),
    Category("bot_check", Policy.UPDATE, "The site wants to check that you aren't a bot. Signing in to the site "
             "usually fixes this.", "signin"),
    Category("rate_limited", Policy.RETRY, "The site is getting too many downloads from you, so the app is waiting "
             "before trying again.", final_message="The site turned away too many downloads. Try again later."),
    Category("private", Policy.SKIP, "This is private."),
    Category("private_signin", Policy.STOP, "This is private. Sign in with an account that can see it.", "signin"),
    Category("no_video", Policy.SKIP, "This post has only pictures, no video."),
    Category("removed", Policy.SKIP, "This was removed or isn't available."),
    Category("geo", Policy.SKIP, "This isn't available in your country."),
    Category("drm", Policy.SKIP, "The site copy-protects this, so it can't be downloaded."),
    Category("format", Policy.SKIP, "This isn't offered in the quality or type you chose. Pick another and try again."),
    # The site gave nothing at all to download (not a choice the user made).
    Category("no_formats", Policy.SKIP, "The site offered nothing to download here. It may be protected or blocked "
             "in your country."),
    Category("empty_tab", Policy.SKIP, "This channel has nothing in that tab."),
    Category("unsupported", Policy.STOP, "The app can't download from this link. Check that it opens a video, song, "
             "or playlist."),
    Category("extractor_broken", Policy.UPDATE, "The site changed and the app couldn't read it. Update the download "
             "tools, then try again.", "update_tools"),
    Category("disk_full", Policy.PAUSE_QUEUE, "The drive is full. Free up some space or choose another folder.",
             "choose_folder"),
    Category("access_denied", Policy.STOP, "The app isn't allowed to save in this folder. Choose another folder.",
             "choose_folder"),
    Category("folder_missing", Policy.STOP, "The download folder can't be reached. Plug in its drive or choose "
             "another folder.", "choose_folder"),
    Category("file_locked", Policy.RETRY, "Another program is using the file; trying again.",
             final_message="Another program kept the file open. Close it and try again."),
    Category("tools", Policy.STOP, "The download tools are missing or damaged. Update them, then try again.",
             "repair_tools"),
    Category("upcoming", Policy.STOP, "This stream hasn't started yet. Try again once it starts, or choose to wait "
             "for it."),
    Category("postprocess", Policy.RETRY, "The file couldn't be finished after downloading; trying again.",
             final_message="The file couldn't be finished after downloading. Try again."),
    # Extracting the audio of a downloaded video (no site involved).
    Category("no_audio", Policy.STOP, "The video has no audio to extract."),
    Category("source_missing", Policy.STOP, "The video file is no longer there."),
    Category("bad_video", Policy.STOP, "The video file couldn't be read. It may be damaged or open in another program."),
    Category("extract_failed", Policy.STOP, "The audio couldn't be extracted. Try again; if it fails again, the video "
             "file may be damaged."),
    # A video's download server that stopped answering (see JobExecutor's stall check).
    Category("stalled", Policy.RETRY, "The download server didn't answer; trying again soon.",
             final_message="The download server didn't answer. Try again later."),
    Category("network", Policy.RETRY, "The connection dropped; trying again.",
             final_message="The connection kept dropping. Check your internet connection and try again."),
    Category("unknown", Policy.RETRY, "Something went wrong; trying again.", "update_tools",
             final_message="Something went wrong with this download. Try again; if it keeps happening, update the "
             "download tools."),
)}

# Ordered: the first matching rule wins, so specific messages come before general ones.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple((key, re.compile(pattern, re.IGNORECASE)) for key, pattern in (
    ("cookies_stale", r"cookies are no longer valid|cookies? (?:have|has) (?:been )?rotated"),
    ("bot_check", r"not a bot|confirm you.?re not a bot"),
    ("auth_required", r"sign in to confirm your age|age.restricted|members.only|join this channel|"
                      r"available to this channel.s members|"
                      r"login required|log in to|requires? (?:a )?(?:login|authentication|subscription)|"
                      r"use --cookies|--cookies-from-browser|private account|nsfw tweet|"
                      r"this video is only available for registered users|logged.in"),
    ("private", r"private video|video is private|this playlist is private"),
    ("no_video", r"there(?:.?s| is) no video in this|no video could be found|(?:post|tweet|pin) (?:has|contains) no video|"
                 r"(?:photo|image|slideshow) posts? (?:are|is) not supported"),
    ("empty_tab", r"this channel does not have an? \w+ tab"),
    ("removed", r"has been removed|video unavailable|this video is unavailable|account .* terminated|"
                r"live stream recording is not available|this live event has ended|"
                r"does not exist|no longer available|has been deleted|copyright claim|"
                r"this channel does not have|HTTP Error 404"),
    ("geo", r"not available in your country|geo.?restrict|blocked it in your country|"
            r"not made this video available in your country"),
    ("drm", r"\bDRM\b"),
    ("upcoming", r"will begin in|premieres? in|this live event will begin|scheduled to start|"
                 r"live stream (?:has )?not (?:yet )?started"),
    ("format", r"requested format is not available"),
    ("no_formats", r"no video formats found|no formats? (?:found|available)"),
    ("unsupported", r"unsupported url|is not a valid url|no suitable (?:extractor|infoextractor)"),
    ("rate_limited", r"HTTP Error 429|too many requests|rate.?limit"),
    ("disk_full", r"no space left|not enough space|disk full|WinError 112|errno 28"),
    ("access_denied", r"WinError 5\b|errno 13|permission denied|access is denied"),
    ("file_locked", r"WinError 32|being used by another process"),
    ("tools", r"ffmpeg (?:is )?not (?:found|installed)|ffprobe (?:is )?not found|"
              r"no supported javascript runtime|js runtime|challenge solver|n challenge solving failed"),
    # A connection cut or blocked on the way (seen with TikTok, which some networks block): yt-dlp
    # words these like its own bugs ("please report this issue"), but updating it doesn't help.
    ("network", r"curl: \(\d+\)|ssl_connect|connection closed abruptly|read timed out"),
    ("bot_check", r"HTTP Error 403"),
    ("extractor_broken", r"unable to extract|please report this issue|unable to download (?:api )?json|"
                         r"failed to parse json|signature extraction failed|nsig extraction failed"),
    ("postprocess", r"conversion failed|postprocessing:|error merging|ffmpeg exited with code"),
    ("network", r"getaddrinfo|timed out|timeout|connection (?:reset|refused|aborted)|10054|10060|10061|"
                r"temporary failure in name resolution|network is unreachable|ssl|"
                r"remote end closed|incomplete read|HTTP Error 5\d\d|unable to connect|"
                r"did not get any data blocks|giving up after \d+ retries"),
))


# What YouTube says about a private playlist, or Watch later and Liked videos, to someone signed out.
_ACCOUNT_LIST = re.compile(r"this playlist is private|the playlist does not exist|playlist.{0,40}private",
                           re.IGNORECASE)


def classify(text: str, item_id: str = "", signed_in: bool = True, single: bool = False) -> Failure:
    """The category of one error message.

    Signed out, a private playlist (or a private single video) may well be the user's own, so it asks
    for a sign-in instead of being skipped. A private video inside a public playlist is still skipped.
    """
    for key, pattern in _RULES:
        if pattern.search(text):
            if not signed_in and (_ACCOUNT_LIST.search(text) or key == "private" and single):
                return Failure(CATEGORIES["private_signin"], text, item_id)
            return Failure(CATEGORIES[key], text, item_id)
    return Failure(CATEGORIES["unknown"], text, item_id)


@dataclass(frozen=True)
class Verdict:
    """What one attempt's failures mean for the job as a whole."""

    policy: Policy
    failures: tuple[Failure, ...]
    skipped_ids: tuple[str, ...]

    @property
    def headline(self) -> Failure | None:
        """The failure that decided the verdict."""
        for failure in self.failures:
            if failure.category.policy == self.policy:
                return failure
        return self.failures[0] if self.failures else None


_SEVERITY = (Policy.PAUSE_QUEUE, Policy.STOP, Policy.UPDATE, Policy.RETRY, Policy.SKIP)


def folder_failure(error: OSError) -> Failure:
    """A download folder that can't be written: the drive is full, the app isn't allowed, or the folder
    isn't there (an unplugged drive, a share that went away)."""
    if error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112):
        return Failure(CATEGORIES["disk_full"], str(error))
    if isinstance(error, PermissionError):
        return Failure(CATEGORIES["access_denied"], str(error))
    return Failure(CATEGORIES["folder_missing"], str(error))


def given_up(failure: Failure) -> Failure:
    """The same failure, now skipped: a playlist's video that failed this way attempt after attempt."""
    return replace(failure, category=replace(failure.category, policy=Policy.SKIP))


def judge(failures: Iterable[Failure]) -> Verdict:
    """Combine an attempt's failures: the most severe policy wins; SKIP only when nothing else failed.

    Items that failed for a permanent reason (private, removed) are listed in skipped_ids so later
    attempts leave them out instead of failing on them forever.
    """
    items = tuple(failures)
    skipped = tuple(dict.fromkeys(f.item_id for f in items if f.category.policy is Policy.SKIP and f.item_id))
    policies = {failure.category.policy for failure in items}
    for policy in _SEVERITY:
        if policy in policies:
            return Verdict(policy, items, skipped)
    return Verdict(Policy.RETRY, items, skipped)
