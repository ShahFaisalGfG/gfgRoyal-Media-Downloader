# subscriptions_ctrl.py - watch channels and playlists, and queue their new uploads on a schedule
#
# A check lists the newest uploads and stops at the first one already in the subscription's
# archive (the same archive a manual download of the channel uses), so nothing downloads twice.
# Scheduled streams and premieres join the queue as waits; items nobody can reach are remembered
# and not reported again. Checks run on the app's timer while it is open or in the tray.

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.core.archive import append_archive, archive_path, read_archive_ids
from gfgmd.core.command import EXIT_BREAK_ON_EXISTING, Auth, check_command, run_marker
from gfgmd.core.errors import CATEGORIES, classify
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import ProgressTracker
from gfgmd.core.runner import run_to_completion
from gfgmd.core.schedule import live_launch_time, next_check
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sources import Source, as_link, check_url, source_from_url
from gfgmd.core.subscriptions import check_urls, parse_takeout, sort_entries
from gfgmd.controllers.queue_ctrl import QueueController, base_options
from gfgmd.models.list_model import DictListModel
from gfgmd.services.context import VAULT_METHODS, AppContext
from gfgmd.services.notifier import Notifier
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.logging import write_log
from gfgmd.utils.settings import load_settings

TIMER_MS = 60_000
MAX_PARALLEL = 2
ROLES = ("subId", "title", "url", "site", "active", "autoDownload", "intervalText", "lastText", "nextText",
         "resultText", "newCount", "checking", "failed")
# What a check that failed shows; the reason, when it is one of the app's own, follows.
_CHECK_FAILED = "Couldn't check for new uploads."
_KNOWN_REASONS = {category.final for category in CATEGORIES.values()}


def _interval(hours: int) -> str:
    """How often a subscription is checked: "Every hour", "Every 6 hours", "Daily"."""
    if hours >= 24:
        return "Daily" if hours == 24 else f"Every {hours // 24} days"
    return "Every hour" if hours == 1 else f"Every {hours} hours"


def _when(timestamp: float) -> str:
    if not timestamp:
        return "Never"
    moment = datetime.fromtimestamp(timestamp)
    return moment.strftime("%H:%M") if moment.date() == datetime.now().date() else moment.strftime("%d %b, %H:%M")


def _already_text(count: int) -> str:
    """" 2 were already in your list." after an import (nothing when there were none)."""
    if not count:
        return ""
    return f" {count} {'was' if count == 1 else 'were'} already in your list."


# The most entries a playlist subscription reads on each check (a playlist is read whole).
PLAYLIST_LIMIT = 2000

def _upload(entry: dict[str, Any], source: Source) -> dict[str, Any]:
    """An upload a check found, as the queue lists it: id, title, link, length, and thumbnail."""
    video_id = str(entry.get("id") or "")
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if source.site == "youtube" and video_id else ""
    return {"id": video_id, "title": str(entry.get("title") or ""), "url": _entry_url(entry, source),
            "duration": entry.get("duration") or 0, "thumbnail": thumbnail}


def _entry_url(entry: dict[str, Any], source: Source) -> str:
    """The upload's own link: an https link the link box would take, or "" when it has none."""
    url = str(entry.get("url") or "")
    if not url.startswith("https://") and source.site == "youtube" and entry.get("id"):
        url = f"https://www.youtube.com/watch?v={entry['id']}"
    try:
        return check_url(url) if url.startswith("https://") else ""
    except ValueError:
        return ""


class SubscriptionsController(QObject):
    """The Subscriptions page and its background checks."""

    changed = Signal()
    notice = Signal(str)

    def __init__(self, context: AppContext, queue: QueueController, notifier: Notifier,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._queue = queue
        self._notifier = notifier
        self._model = DictListModel(ROLES, "subId", self)
        self._runner = TaskRunner(MAX_PARALLEL, self)
        self._checking: set[int] = set()
        self._stop = threading.Event()
        self._last_site_check: dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TIMER_MS)
        self._timer.timeout.connect(self._check_due)
        self._timer.start()
        self._sync()

    @Property(QObject, constant=True)
    def model(self) -> DictListModel:
        return self._model

    @Property(int, notify=changed)
    def count(self) -> int:
        return self._model.rowCount()

    # ── Managing subscriptions ────────────────────────────────────────────

    @Slot(str, result=str)
    def linkProblem(self, url: str) -> str:
        """Why this link can't be subscribed to, or "" when it can (the Subscribe dialog asks first)."""
        url = as_link(url)
        try:
            source = source_from_url(url)
        except ValueError as error:
            return str(error)
        if not source.is_collection:
            return "Subscribe to a channel or a playlist, not a single video."
        if self._subscribed(url):
            return "You're already subscribed to this."
        return ""

    def _subscribed(self, url: str) -> bool:
        """True when this link is watched already."""
        url = as_link(url)
        return any(sub["url"] == url for sub in self._context.store.subscriptions())

    @Slot(str, "QVariantMap", int, bool, bool, result=bool)
    def add(self, url: str, options: dict[str, Any], interval_hours: int, download_existing: bool,
            auto_download: bool) -> bool:
        """Watch a channel or playlist. Without download_existing, only uploads from now on download."""
        problem = self.linkProblem(url)
        if problem:
            self.notice.emit(problem)
            return False
        return self._subscribe(as_link(url), options, interval_hours, download_existing, auto_download)

    def _subscribe(self, url: str, options: dict[str, Any], interval_hours: int, download_existing: bool,
                   auto_download: bool) -> bool:
        """Add a subscription to a checked link (see linkProblem); False when the link can't be used or
        is already watched (an import run twice must not start an existing one over)."""
        try:
            source = source_from_url(url)
        except ValueError:
            return False
        if self._subscribed(url):
            return False
        if not source.is_collection:
            return False
        picked = DownloadOptions.from_dict({**base_options(load_settings()).to_dict(), **options})
        chosen = picked.to_dict()
        url = url.strip()
        account = self._context.account_for(source.site)
        sub_id = self._context.store.add_subscription(
            url, "", source.site, chosen, str(self._context.download_root(picked.kind)), interval_hours, auto_download,
            account["id"] if account else None, time.time() + 3600)
        if download_existing:
            self._queue.addJob(url, chosen, [], "", "", 0.0)
            self._context.store.update_subscription(sub_id, next_check=next_check(time.time(), interval_hours))
            self._sync()
        else:
            self._start_check(sub_id, seed=True)
        return True

    @Slot(int)
    def remove(self, sub_id: int) -> None:
        """Stop watching (downloaded files and the archive stay)."""
        self._context.store.delete_subscription(sub_id)
        self._sync()

    @Slot(int, bool)
    def setEnabled(self, sub_id: int, enabled: bool) -> None:
        self._context.store.update_subscription(sub_id, enabled=int(enabled))
        self._sync()

    @Slot(int, bool)
    def setAutoDownload(self, sub_id: int, auto: bool) -> None:
        self._context.store.update_subscription(sub_id, auto_download=int(auto))
        self._sync()

    @Slot(int, int)
    def setInterval(self, sub_id: int, hours: int) -> None:
        self._context.store.update_subscription(sub_id, interval_hours=hours,
                                                next_check=next_check(time.time(), hours))
        self._sync()

    @Slot(int)
    def checkNow(self, sub_id: int) -> None:
        self._start_check(sub_id)

    @Slot()
    def checkAll(self) -> None:
        """Check every enabled subscription now (two at a time)."""
        for sub in self._context.store.subscriptions():
            if sub["enabled"]:
                self._start_check(sub["id"])

    @Slot(int)
    def downloadNew(self, sub_id: int) -> None:
        """Queue the new uploads a subscription without automatic downloads has found."""
        sub = self._context.store.subscription(sub_id)
        if sub is None:
            return
        store = self._context.store
        source = source_from_url(sub["url"])
        uploads = [_upload(dict(row), source) for row in store.pending_uploads(sub_id)]
        ready = [upload for upload in uploads if upload["url"]]
        options = DownloadOptions.from_dict(json.loads(sub["options_json"]))
        self._queue.add_subscription_items(ready, source, options, sub_id, sub["account_id"],
                                           title=sub["title"], url=sub["url"], folder=self._folder(sub, source))
        store.mark_seen(sub_id, [upload["id"] for upload in ready], "queued")
        if len(ready) < len(uploads):
            write_log(f"{len(uploads) - len(ready)} new upload(s) of {sub['url']} had no link to download", "general")
        store.mark_seen(sub_id, [upload["id"] for upload in uploads if not upload["url"]], "skipped")
        store.update_subscription(sub_id, new_count=0)
        self._sync()

    @Slot(str, result=int)
    def importTakeout(self, text: str) -> int:
        """Subscribe to every channel in YouTube Takeout's subscriptions.csv (only new uploads)."""
        try:
            pairs = parse_takeout(text)
        except ValueError as error:
            self.notice.emit(str(error))
            return 0
        hours = int(load_settings().get("subscriptions", {}).get("interval_hours", 6))
        auto = bool(load_settings().get("subscriptions", {}).get("auto_download", True))
        links = [url + "/videos" for url, _title in pairs]
        already = sum(1 for url in links if self._subscribed(url))
        added = sum(1 for url in links if self._subscribe(url, {}, hours, False, auto))
        self.notice.emit(f"Subscribed to {added} channel{'s' if added != 1 else ''}." + _already_text(already))
        return added

    @Slot(result=str)
    def exportJson(self) -> str:
        """Every subscription as JSON text (for backup or another PC)."""
        rows = [{"url": s["url"], "title": s["title"], "interval_hours": s["interval_hours"],
                 "auto_download": bool(s["auto_download"]), "enabled": bool(s["enabled"]),
                 "options": json.loads(s["options_json"])} for s in self._context.store.subscriptions()]
        return json.dumps({"app": "gfgRoyal Media Downloader", "subscriptions": rows}, indent=2)

    @Slot(str, result=int)
    def importJson(self, text: str) -> int:
        """Subscribe to the channels in an exported file (only new uploads)."""
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        rows = data.get("subscriptions") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            self.notice.emit("That file isn't a subscriptions export from this app.")
            return 0
        added = 0
        already = sum(1 for row in rows if isinstance(row, dict) and self._subscribed(str(row.get("url") or "")))
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("url"), str):
                options: dict[str, Any] = row["options"] if isinstance(row.get("options"), dict) else {}
                hours = int(row.get("interval_hours", 6)) if isinstance(row.get("interval_hours"), int) else 6
                added += self._subscribe(row["url"], options, hours, False, bool(row.get("auto_download", True)))
        self.notice.emit(f"Restored {added} subscription{'s' if added != 1 else ''}." + _already_text(already))
        return added

    # ── Checking ──────────────────────────────────────────────────────────

    def _check_due(self) -> None:
        now = time.time()
        for sub in self._context.store.due_subscriptions(now):
            if len(self._checking) >= MAX_PARALLEL:
                break
            # Politeness: at least ten seconds between checks to one site.
            if now - self._last_site_check.get(sub["site"], 0) < 10:
                continue
            self._start_check(sub["id"])

    def _start_check(self, sub_id: int, seed: bool = False) -> None:
        sub = self._context.store.subscription(sub_id)
        if sub is None or sub_id in self._checking:
            return
        try:
            tools = self._context.tools()
        except RuntimeError as error:
            write_log(f"Subscription check {sub_id} can't start: {error}", "critical")
            self._context.store.update_subscription(
                sub_id, last_result=f"{_CHECK_FAILED} The download tools aren't installed yet.")
            self._sync()
            return
        self._checking.add(sub_id)
        self._last_site_check[sub["site"]] = time.time()
        self._sync()
        self._runner.start(self._check, sub, tools, seed,
                           on_done=lambda result, s=sub_id: self._checked(s, result),
                           on_error=lambda message, s=sub_id: self._failed(s, message))

    def _check(self, sub: dict[str, Any], tools: Any, seed: bool) -> dict[str, Any]:
        """On the pool: list the newest uploads that aren't in the archive."""
        context = self._context
        source = source_from_url(sub["url"])
        options = DownloadOptions.from_dict(json.loads(sub["options_json"]))
        archive = archive_path(Path(sub["output_root"]), source, options.profile)
        job_dir = context.jobs_root / f"subscription-{sub['id']}"
        job_dir.mkdir(parents=True, exist_ok=True)
        account = context.account_for(sub["site"], sub["account_id"])
        auth: Auth | None = context.browser_auth(account)
        checkout = None
        if account is not None and account["method"] in VAULT_METHODS and context.vault.exists(account["id"]):
            try:
                checkout = context.vault.checkout(account["id"], context.site(sub["site"]),
                                                  context.run_root / f"sub-{sub['id']}-{int(time.time())}")
                auth = Auth(cookies_file=str(checkout.path))
            except (SecretError, OSError, TimeoutError):
                checkout = None
        marker = run_marker()
        tracker = ProgressTracker(marker=marker)
        try:
            # A playlist is read whole (its new videos are added at the end); a channel newest first.
            whole = source.kind not in ("channel", "profile")
            command, batch = check_command(check_urls(source, sub["url"]), tools, archive, context.cache_dir,
                                           job_dir, auth, newest=PLAYLIST_LIMIT if whole else 200 if seed else 60,
                                           marker=marker, whole=whole)
            if batch:
                (job_dir / "urls.txt").write_text(batch, encoding="utf-8")
            code, _ = run_to_completion(command, tracker.feed, self._stop)
        finally:
            if checkout is not None and account is not None:
                context.vault.checkin(account["id"], checkout)
        if code not in (0, EXIT_BREAK_ON_EXISTING) and not tracker.entries:
            reason = tracker.errors[-1].text if tracker.errors else f"yt-dlp exited with status {code}"
            write_log(f"Subscription check of {sub['url']} failed: {reason}", "critical")
            raise RuntimeError(classify(reason).category.final)
        result = sort_entries(tracker.entries, read_archive_ids(archive), context.store.seen(sub["id"]))
        listing = tracker.playlist
        # A playlist is called by its own name; a channel (a tab such as "Name - Videos") by its owner's.
        names = ("title", "channel", "uploader") if source.kind == "playlist" else ("channel", "uploader", "title")
        title = next((str(listing[name]) for name in names if listing.get(name)), "") or sub["title"]
        if seed:
            extractor = str(next((e.get("ie_key") for e in tracker.entries if e.get("ie_key")), source.site))
            seeded = append_archive(archive, extractor, [str(e["id"]) for e in result.new])
            context.store.mark_seen(sub["id"], [str(e["id"]) for e in result.upcoming + result.unreachable], "skipped")
            return {"title": title, "seeded": seeded, "new": [], "upcoming": [], "unreachable": []}
        return {"title": title, "seeded": 0, "new": result.new, "upcoming": result.upcoming,
                "unreachable": result.unreachable, "list_title": str(listing.get("title") or "")}

    def _folder(self, sub: dict[str, Any], source: Source, list_title: str = "") -> str:
        """The folder a YouTube playlist's uploads go in, named outright: its own links carry no playlist name.

        Channels need none; each video names its channel.
        """
        if source.kind != "playlist" or source.site != "youtube":
            return ""
        return list_title or sub["title"]

    def _checked(self, sub_id: int, result: dict[str, Any]) -> None:
        self._checking.discard(sub_id)
        sub = self._context.store.subscription(sub_id)
        if sub is None:
            self._sync()
            return
        source = source_from_url(sub["url"])
        options = DownloadOptions.from_dict(json.loads(sub["options_json"]))
        store = self._context.store
        new = [entry for entry in result["new"] if _entry_url(entry, source)]
        folder = self._folder(sub, source, str(result.get("list_title") or ""))
        if new and sub["auto_download"]:
            self._queue.add_subscription_items([_upload(e, source) for e in new], source, options, sub_id,
                                               sub["account_id"], title=result["title"] or sub["title"],
                                               url=sub["url"], folder=folder)
            store.mark_seen(sub_id, [str(e["id"]) for e in new], "queued")
        elif new:
            store.mark_pending(sub_id, [_upload(e, source) for e in new])
        live_options = options.with_changes(wait_for_video=True, live_from_start=source.site == "youtube")
        for entry in result["upcoming"]:
            when = float(entry.get("release_timestamp") or 0)
            self._queue.add_subscription_items([_upload(entry, source)], source, live_options, sub_id,
                                               sub["account_id"], live_launch_time(when, time.time()) if when else 0.0,
                                               folder=folder)
        store.mark_seen(sub_id, [str(e["id"]) for e in result["upcoming"]], "upcoming")
        store.mark_seen(sub_id, [str(e["id"]) for e in result["unreachable"]], "skipped")
        pending = sum(1 for status in store.seen(sub_id).values() if status == "pending")
        if result["seeded"]:
            seeded = int(result["seeded"])
            summary = f"Watching from now on ({seeded} earlier upload{'s' if seeded != 1 else ''} skipped)"
        elif new:
            uploads = f"{len(new)} new upload{'s' if len(new) != 1 else ''}"
            summary = uploads + (" added to Downloads" if sub["auto_download"] else " found")
        else:
            summary = "No new uploads"
        store.update_subscription(sub_id, title=result["title"][:200], last_check=time.time(),
                                  next_check=next_check(time.time(), sub["interval_hours"]), last_result=summary,
                                  new_count=pending)
        if new and load_settings().get("notifications", {}).get("enabled", True):
            self._notifier.notify("New uploads", f"{result['title']}: {summary}")
        self._sync()

    def _failed(self, sub_id: int, message: str) -> None:
        self._checking.discard(sub_id)
        sub = self._context.store.subscription(sub_id)
        if sub is not None:
            # Try again sooner than the full interval, but not in a tight loop.
            again = datetime.fromtimestamp(time.time() + 1800).strftime("%H:%M")
            reason = f" {message}" if message in _KNOWN_REASONS else ""
            self._context.store.update_subscription(sub_id, last_check=time.time(),
                                                    last_result=f"{_CHECK_FAILED}{reason} Trying again at {again}.",
                                                    next_check=time.time() + 1800)
        write_log(f"Subscription check {sub_id} failed: {message}", "critical")
        self._sync()

    def _sync(self) -> None:
        rows = []
        for sub in self._context.store.subscriptions():
            rows.append({
                "subId": sub["id"], "title": sub["title"] or sub["url"], "url": sub["url"],
                "site": self._context.site(sub["site"]).label, "active": bool(sub["enabled"]),
                "autoDownload": bool(sub["auto_download"]),
                "intervalText": _interval(sub["interval_hours"]),
                "lastText": _when(sub["last_check"]),
                "nextText": _when(sub["next_check"]) if sub["enabled"] else "Off",
                "resultText": sub["last_result"], "newCount": sub["new_count"],
                "checking": sub["id"] in self._checking,
                "failed": str(sub["last_result"]).startswith(_CHECK_FAILED),
            })
        self._model.sync(rows)
        self.changed.emit()

    def shutdown(self) -> None:
        self._timer.stop()
        self._stop.set()
        self._runner.shutdown(3000)
