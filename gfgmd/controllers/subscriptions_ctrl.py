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
from gfgmd.core.command import EXIT_BREAK_ON_EXISTING, Auth, check_command
from gfgmd.core.errors import classify
from gfgmd.core.options import DownloadOptions
from gfgmd.core.progress import ProgressTracker
from gfgmd.core.runner import run_to_completion
from gfgmd.core.schedule import live_launch_time, next_check
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sources import Source, source_from_url
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
         "resultText", "newCount", "checking")


def _when(timestamp: float) -> str:
    if not timestamp:
        return "Never"
    moment = datetime.fromtimestamp(timestamp)
    return moment.strftime("%H:%M") if moment.date() == datetime.now().date() else moment.strftime("%d %b, %H:%M")


def _entry_url(entry: dict[str, Any], source: Source) -> str:
    url = str(entry.get("url") or "")
    if url.startswith("https://"):
        return url
    if source.site == "youtube" and entry.get("id"):
        return f"https://www.youtube.com/watch?v={entry['id']}"
    return url


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

    @Slot(str, "QVariantMap", int, bool, bool, result=bool)
    def add(self, url: str, options: dict[str, Any], interval_hours: int, download_existing: bool,
            auto_download: bool) -> bool:
        """Watch a channel or playlist. Without download_existing, only uploads from now on download."""
        try:
            source = source_from_url(url)
        except ValueError as error:
            self.notice.emit(str(error))
            return False
        if not source.is_collection:
            self.notice.emit("Subscribe to a channel or a playlist, not a single video.")
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
        pending = [video_id for video_id, status in self._context.store.seen(sub_id).items() if status == "pending"]
        source = source_from_url(sub["url"])
        urls = [f"https://www.youtube.com/watch?v={video_id}" if source.site == "youtube" else video_id
                for video_id in pending]
        options = DownloadOptions.from_dict(json.loads(sub["options_json"]))
        self._queue.add_subscription_items([u for u in urls if u.startswith("https://")], source, options, sub_id,
                                           sub["account_id"])
        self._context.store.mark_seen(sub_id, pending, "queued")
        self._context.store.update_subscription(sub_id, new_count=0)
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
        added = sum(1 for url, _title in pairs if self.add(url + "/videos", {}, hours, False, auto))
        self.notice.emit(f"Subscribed to {added} channel(s).")
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
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("url"), str):
                options: dict[str, Any] = row["options"] if isinstance(row.get("options"), dict) else {}
                hours = int(row.get("interval_hours", 6)) if isinstance(row.get("interval_hours"), int) else 6
                added += bool(self.add(row["url"], options, hours, False, bool(row.get("auto_download", True))))
        self.notice.emit(f"Subscribed to {added} channel(s) or playlist(s).")
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
            self._context.store.update_subscription(sub_id, last_result=str(error))
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
        command, batch = check_command(check_urls(source, sub["url"]), tools, archive, context.cache_dir, job_dir,
                                       auth, newest=200 if seed else 60)
        if batch:
            (job_dir / "urls.txt").write_text(batch, encoding="utf-8")
        tracker = ProgressTracker()
        try:
            code, _ = run_to_completion(command, tracker.feed, self._stop)
        finally:
            if checkout is not None and account is not None:
                context.vault.checkin(account["id"], checkout)
        if code not in (0, EXIT_BREAK_ON_EXISTING) and not tracker.entries:
            reason = tracker.errors[-1].text if tracker.errors else f"yt-dlp exited with status {code}"
            raise RuntimeError(classify(reason).category.message)
        result = sort_entries(tracker.entries, read_archive_ids(archive), context.store.seen(sub["id"]))
        listing = tracker.playlist
        title = str(listing.get("channel") or listing.get("uploader") or listing.get("title") or sub["title"]
                    or sub["url"])
        if seed:
            extractor = str(next((e.get("ie_key") for e in tracker.entries if e.get("ie_key")), source.site))
            seeded = append_archive(archive, extractor, [str(e["id"]) for e in result.new])
            context.store.mark_seen(sub["id"], [str(e["id"]) for e in result.upcoming + result.unreachable], "skipped")
            return {"title": title, "seeded": seeded, "new": [], "upcoming": [], "unreachable": []}
        return {"title": title, "seeded": 0, "new": result.new, "upcoming": result.upcoming,
                "unreachable": result.unreachable}

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
        if new and sub["auto_download"]:
            self._queue.add_subscription_items([_entry_url(e, source) for e in new], source, options, sub_id,
                                               sub["account_id"])
            store.mark_seen(sub_id, [str(e["id"]) for e in new], "queued")
        elif new:
            store.mark_seen(sub_id, [str(e["id"]) for e in new], "pending")
        live_options = options.with_changes(wait_for_video=True, live_from_start=source.site == "youtube")
        for entry in result["upcoming"]:
            when = float(entry.get("release_timestamp") or 0)
            self._queue.add_subscription_items([_entry_url(entry, source)], source, live_options, sub_id,
                                               sub["account_id"], live_launch_time(when, time.time()) if when else 0.0)
        store.mark_seen(sub_id, [str(e["id"]) for e in result["upcoming"]], "upcoming")
        store.mark_seen(sub_id, [str(e["id"]) for e in result["unreachable"]], "skipped")
        pending = sum(1 for status in store.seen(sub_id).values() if status == "pending")
        if result["seeded"]:
            summary = f"Watching from now on ({result['seeded']} earlier uploads skipped)"
        elif new:
            summary = f"{len(new)} new upload(s)" + (" queued" if sub["auto_download"] else " found")
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
            self._context.store.update_subscription(sub_id, last_check=time.time(),
                                                    last_result=f"Check failed: {message}",
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
                "intervalText": f"Every {sub['interval_hours']} h" if sub["interval_hours"] < 24 else "Daily",
                "lastText": _when(sub["last_check"]),
                "nextText": _when(sub["next_check"]) if sub["enabled"] else "Off",
                "resultText": sub["last_result"], "newCount": sub["new_count"],
                "checking": sub["id"] in self._checking,
            })
        self._model.sync(rows)
        self.changed.emit()

    def shutdown(self) -> None:
        self._timer.stop()
        self._stop.set()
        self._runner.shutdown(3000)
