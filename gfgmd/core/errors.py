"""Sort yt-dlp's error messages into categories that decide whether to retry, skip, or ask the user."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
    """One kind of failure and what the app does about it."""

    key: str
    policy: Policy
    message: str
    action: str = ""  # the button the UI offers: signin, update_tools, choose_folder, repair_tools


@dataclass(frozen=True)
class Failure:
    """One classified error line."""

    category: Category
    text: str
    item_id: str = ""


CATEGORIES = {category.key: category for category in (
    Category("auth_required", Policy.STOP, "This video needs you to sign in to the site", "signin"),
    Category("cookies_stale", Policy.STOP, "The saved sign-in has expired; sign in again", "signin"),
    Category("bot_check", Policy.UPDATE, "The site asked to confirm you are not a bot", "signin"),
    Category("rate_limited", Policy.RETRY, "The site is limiting requests; waiting before trying again"),
    Category("private", Policy.SKIP, "Private video"),
    Category("private_signin", Policy.STOP, "This is private. Sign in with an account that can see it", "signin"),
    Category("no_video", Policy.SKIP, "This post has only pictures, no video"),
    Category("removed", Policy.SKIP, "The video was removed or is unavailable"),
    Category("geo", Policy.SKIP, "Not available in your country"),
    Category("drm", Policy.SKIP, "Protected with DRM, which can't be downloaded"),
    Category("format", Policy.SKIP, "No format matches the chosen quality and type"),
    Category("unsupported", Policy.STOP, "This link isn't supported"),
    Category("extractor_broken", Policy.UPDATE, "yt-dlp couldn't read the page; it may need an update",
             "update_tools"),
    Category("disk_full", Policy.PAUSE_QUEUE, "The disk is full", "choose_folder"),
    Category("access_denied", Policy.STOP, "Windows refused to write to the download folder", "choose_folder"),
    Category("file_locked", Policy.RETRY, "Another program has the file open"),
    Category("tools", Policy.STOP, "A required tool is missing or damaged", "repair_tools"),
    Category("upcoming", Policy.STOP, "The stream or premiere hasn't started yet"),
    Category("postprocess", Policy.RETRY, "Converting or merging failed"),
    Category("network", Policy.RETRY, "The connection failed; trying again"),
    Category("unknown", Policy.RETRY, "The download failed"),
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
    ("removed", r"has been removed|video unavailable|this video is unavailable|account .* terminated|"
                r"does not exist|no longer available|has been deleted|copyright claim|"
                r"this channel does not have|HTTP Error 404"),
    ("geo", r"not available in your country|geo.?restrict|blocked it in your country|"
            r"not made this video available in your country"),
    ("drm", r"\bDRM\b"),
    ("upcoming", r"will begin in|premieres? in|this live event will begin|scheduled to start|"
                 r"live stream (?:has )?not (?:yet )?started"),
    ("format", r"requested format is not available|no video formats found|no formats? (?:found|available)"),
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
