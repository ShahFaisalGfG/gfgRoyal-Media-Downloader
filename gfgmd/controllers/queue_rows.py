# queue_rows.py - the Downloads list's rows: one per download, and one per video of an open playlist
#
# Pure functions from stored jobs, their items, and live progress to the values QML shows, kept apart
# from the queue's running logic. Every row carries every role (blank where it doesn't apply), since
# QML reads them by name whichever row it draws.

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from gfgmd.core.naming import format_label
from gfgmd.core.progress import PHASE_DOWNLOAD, PHASE_POST, PHASE_WAIT, Snapshot
from gfgmd.utils.format import about_time, format_bytes, format_time_left, media_noun

ROLES = ("rowKey", "rowType", "jobId", "itemId", "number", "title", "url", "site", "kind", "thumbnail", "jobState",
         "entryState", "statusText", "progress", "detail", "itemText", "message", "action", "folder", "lastFile",
         "canPause", "canResume", "canRetry", "canRedownload", "entryCount", "savedCount", "expanded", "format")
BLANK: dict[str, Any] = {
    "rowKey": "", "rowType": "job", "jobId": 0, "itemId": "", "number": 0, "title": "", "url": "", "site": "",
    "kind": "video", "thumbnail": "", "jobState": "", "entryState": "", "statusText": "", "progress": 0.0,
    "detail": "", "itemText": "", "message": "", "action": "", "folder": "", "lastFile": "", "canPause": False,
    "canResume": False, "canRetry": False, "canRedownload": False, "entryCount": 0, "savedCount": 0,
    "expanded": False, "format": "",
}
# Jobs still to finish: their waiting videos say "Waiting"; once a job has ended they say "Not downloaded".
ACTIVE = ("queued", "scheduled", "waiting_live", "running", "paused", "retry_wait", "needs_auth")
# Sizes under this are yt-dlp's opening estimate from the first part of a download, not the file's size.
# Item states that count as finished for a playlist's progress.
FINISHED_ITEMS = ("done", "archived", "skipped")
STATE_TEXT = {
    "queued": "Waiting to start", "scheduled": "Scheduled", "waiting_live": "Waiting for the stream to start",
    "running": "Starting", "paused": "Paused", "retry_wait": "Trying again soon", "needs_auth": "Sign-in needed",
    "failed": "Failed", "done": "Done", "cancelled": "Cancelled",
}
_ENTRY_TEXT = {
    "done": "Saved", "archived": "Downloaded before", "skipped": "Skipped", "failed": "Couldn't download",
    "deferred": "Waiting for its server",
}


def job_key(job_id: int) -> str:
    """The list key of a download's row."""
    return f"j{job_id}"


def entry_key(job_id: int, item_id: str) -> str:
    """The list key of one video's row under its playlist."""
    return f"e{job_id}:{item_id}"


def kind_of(options: dict[str, Any]) -> str:
    """"audio", "video", or "live" (a stream recorded as it plays) for a job's options."""
    if options.get("live_from_start") or options.get("wait_for_video"):
        return "live"
    return str(options.get("kind", "video"))


def running_values(snap: Snapshot) -> dict[str, Any]:
    """What one downloading video shows: its step, its progress (-1: unknown), and sizes, speed, and time left."""
    parts: list[str] = []
    stage = snap.stage
    if snap.stage == "Saved":
        progress = 1.0
    elif snap.is_live or snap.phase == PHASE_WAIT or not snap.phase:
        progress = -1.0
        if snap.phase == PHASE_WAIT and snap.wait_seconds >= 0 and snap.stage.startswith("Waiting for the stream"):
            stage = f"{snap.stage} ({about_time(snap.wait_seconds)})"
    elif snap.phase == PHASE_POST:
        progress = snap.convert_fraction if snap.convert_fraction >= 0 else -1.0
        if snap.convert_fraction >= 0:
            parts.append(f"{int(snap.convert_fraction * 100)}%")
        if snap.downloaded:
            parts.append(f"{format_bytes(snap.downloaded)} downloaded")
    else:
        moving = snap.downloaded > 0 or snap.total > 0 or snap.item_fraction > 0
        progress = snap.item_fraction if moving and stage != "Connection trouble, trying again" else -1.0
        if snap.size_guessed:
            pass
        elif snap.total:
            parts.append(f"{format_bytes(snap.downloaded)} of {format_bytes(snap.total)}")
        elif snap.downloaded:
            parts.append(format_bytes(snap.downloaded))
        if snap.speed:
            parts.append(f"{format_bytes(int(snap.speed))}/s")
    if snap.eta >= 0 and not snap.is_live and snap.phase in (PHASE_DOWNLOAD, PHASE_POST):
        parts.append(format_time_left(snap.eta))
    if snap.phase == PHASE_WAIT and snap.reason:
        parts.append(snap.reason)
    return {"statusText": stage, "progress": progress, "detail": "  ·  ".join(parts)}


def collection_values(snap: Snapshot, counts: dict[str, int], total: int, kind: str, number: int) -> dict[str, Any]:
    """What a downloading playlist shows: its step, which video, how many are saved, and steady progress.

    Progress counts the videos finished in any attempt, so a restart doesn't send the bar back.
    """
    finished = sum(counts.get(state, 0) for state in FINISHED_ITEMS)
    current = 0.0
    if snap.phase == PHASE_DOWNLOAD:
        current = snap.item_fraction
    elif snap.phase == PHASE_POST and snap.convert_fraction >= 0:
        current = snap.convert_fraction
    progress = min((finished + current) / total, 1.0) if total else (-1.0 if snap.phase == PHASE_WAIT else snap.overall)
    parts: list[str] = []
    saved = counts.get("done", 0)
    if saved:
        parts.append(f"{saved} saved")
    if snap.speed and snap.phase == PHASE_DOWNLOAD:
        parts.append(f"{format_bytes(int(snap.speed))}/s")
    if snap.phase == PHASE_WAIT and snap.reason:
        parts.append(snap.reason)
    noun = media_noun(kind if kind == "audio" else "video").capitalize()
    item = f"{noun} {number} of {total}" if number and total and snap.phase != PHASE_WAIT else ""
    return {"statusText": snap.stage, "progress": progress, "detail": "  ·  ".join(parts), "itemText": item}


def job_row(job: dict[str, Any], site_label: str, last_file: str, counts: dict[str, int], expanded: bool,
            noun_kind: str) -> dict[str, Any]:
    """One download's row as stored (a running one gets its live values on top)."""
    options = json.loads(job["options_json"])
    state = job["state"]
    detail = job["message"] or site_label
    if state in ("scheduled", "waiting_live") and job["not_before"]:
        detail = "Starts " + datetime.fromtimestamp(job["not_before"]).strftime("%A at %H:%M")
    total = int(job["items_total"] or 0)
    total = total if total > 1 else 0  # a list of one is that one video
    finished = sum(counts.get(name, 0) for name in FINISHED_ITEMS)
    if state == "done":
        progress = 1.0
    else:
        progress = finished / total if total else 0.0
    return {
        **BLANK,
        "rowKey": job_key(job["id"]), "rowType": "job", "jobId": job["id"], "title": job["title"] or "Reading the link...",
        "url": job["url"], "site": site_label, "kind": kind_of(options), "thumbnail": job["thumbnail"],
        "jobState": state, "statusText": STATE_TEXT.get(state, ""), "progress": progress, "detail": detail,
        "message": job["message"], "action": job["action"], "folder": job["output_root"], "lastFile": last_file,
        "canPause": state in ("queued", "scheduled", "waiting_live", "running", "retry_wait"),
        "canResume": state in ("paused", "cancelled"),
        # A finished download can only gain from Try again when something in it was skipped.
        "canRetry": state in ("failed", "needs_auth")
        or (state == "done" and (counts.get("skipped", 0) > 0 or job["skip_ids_json"] not in ("", "[]"))),
        "canRedownload": state == "done" and not job["input_path"],
        "entryCount": total, "savedCount": counts.get("done", 0), "expanded": expanded and total > 0,
        "format": format_label(last_file, options),
        "itemText": "" if not total or state == "done" else f"{finished} of {total} {media_noun(noun_kind, total)}",
    }


def entry_row(job: dict[str, Any], item: dict[str, Any], number: int, kind: str, saved_file: str,
              snap: Snapshot | None) -> dict[str, Any]:
    """One video of a playlist, under its download's row."""
    state = str(item["state"])
    active = job["state"] in ACTIVE
    row = {
        **BLANK,
        "rowKey": entry_key(job["id"], item["item_id"]), "rowType": "entry", "jobId": job["id"],
        "itemId": item["item_id"], "number": number, "title": item["title"] or "Untitled",
        "url": item["url"], "kind": kind, "thumbnail": item["thumbnail"], "jobState": job["state"],
        "entryState": state, "lastFile": saved_file,
        "format": format_label(saved_file, json.loads(job["options_json"])) if saved_file else "",
    }
    if snap is not None and snap.item_id == item["item_id"] and state not in ("done", "skipped"):
        row.update(running_values(snap))
        row["entryState"] = "active"
        return row
    if state == "pending":
        row["statusText"] = "Waiting" if active else "Not downloaded"
    else:
        row["statusText"] = _ENTRY_TEXT.get(state, "")
        row["progress"] = 1.0 if state in ("done", "archived") else 0.0
        if state == "deferred":
            row["detail"] = "It gets another try after the rest" if active else ""
        elif state in ("skipped", "failed"):
            row["detail"] = str(item["message"] or "")
    return row
