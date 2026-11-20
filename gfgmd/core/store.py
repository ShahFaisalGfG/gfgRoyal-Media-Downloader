"""The library database: the download queue, finished files, subscriptions, and sign-in records.

SQLite in WAL mode survives crashes and power cuts without a damaged file; every write is a short
transaction. One connection is shared behind a lock, which keeps the thread rules simple: the
queue's workers, the UI, and the subscription checker all go through these methods. Secrets never
enter this database; sign-in cookies live in encrypted files (see secrets.py).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

# The layout number older versions check: one that sees a higher number refuses the library. Raise it
# only for a change an older version would misread; columns it doesn't know it ignores, so those are
# added without raising it (see _add_columns) and 1.0.0 still opens a library a newer version used.
SCHEMA_VERSION = 2

# Playback positions kept (the newest ones).
MAX_POSITIONS = 2000
_PLAYBACK = """
CREATE TABLE IF NOT EXISTS playback (
    filepath TEXT PRIMARY KEY,
    position REAL NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    updated REAL NOT NULL
);
"""

ACTIVE_STATES = ("queued", "scheduled", "waiting_live", "running", "paused", "retry_wait", "needs_auth")
FINISHED_STATES = ("failed", "done", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    site TEXT NOT NULL,
    tab TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL,
    output_root TEXT NOT NULL,
    input_path TEXT NOT NULL DEFAULT '',
    account_id INTEGER,
    subscription_id INTEGER,
    state TEXT NOT NULL,
    position REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    error_key TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    files_done INTEGER NOT NULL DEFAULT 0,
    items_total INTEGER NOT NULL DEFAULT 0,
    skip_ids_json TEXT NOT NULL DEFAULT '[]',
    created REAL NOT NULL,
    updated REAL NOT NULL,
    finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_by_state ON jobs (state, position);
CREATE TABLE IF NOT EXISTS job_items (
    job_id INTEGER NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    duration REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'pending',
    message TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job_id, item_id)
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY,
    job_id INTEGER,
    video_id TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'video',
    title TEXT NOT NULL DEFAULT '',
    uploader TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    filepath TEXT NOT NULL UNIQUE,
    height INTEGER NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0,
    thumbnail TEXT NOT NULL DEFAULT '',
    finished REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS history_by_time ON history (finished DESC);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    site TEXT NOT NULL DEFAULT '',
    options_json TEXT NOT NULL,
    output_root TEXT NOT NULL,
    interval_hours INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_download INTEGER NOT NULL DEFAULT 1,
    account_id INTEGER,
    last_check REAL NOT NULL DEFAULT 0,
    next_check REAL NOT NULL DEFAULT 0,
    last_result TEXT NOT NULL DEFAULT '',
    new_count INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_seen (
    sub_id INTEGER NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    video_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (sub_id, video_id)
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    method TEXT NOT NULL,
    browser TEXT NOT NULL DEFAULT '',
    domains_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ok',
    created REAL NOT NULL,
    refreshed REAL NOT NULL,
    expires REAL NOT NULL DEFAULT 0
);
"""

_JOB_FIELDS = {"title", "thumbnail", "options_json", "output_root", "account_id", "state", "position", "attempts",
               "not_before", "message", "error_key", "action", "files_done", "items_total", "skip_ids_json",
               "finished", "url"}
_SUB_FIELDS = {"title", "site", "options_json", "output_root", "interval_hours", "enabled", "auto_download",
               "account_id", "last_check", "next_check", "last_result", "new_count"}
_ACCOUNT_FIELDS = {"label", "method", "browser", "domains_json", "status", "refreshed", "expires"}


class Store:
    """Thread-safe access to library.db."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._migrate()

    def close(self) -> None:
        """Close the database."""
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError("The library was created by a newer version of the app")
        if version < 1:
            self._db.executescript("BEGIN;" + _SCHEMA + _PLAYBACK + f"PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
            return
        if version < 2:
            # Version 2 remembers where playback stopped in each file.
            self._db.executescript("BEGIN;" + _PLAYBACK + "PRAGMA user_version = 2; COMMIT;")
        self._add_columns()
        # 1.0.0 left records naming jobs it had removed; they belong to no job.
        self._db.execute("UPDATE history SET job_id = NULL WHERE job_id IS NOT NULL AND job_id NOT IN "
                         "(SELECT id FROM jobs)")

    def _add_columns(self) -> None:
        """Add the columns made after 1.0.0, which 1.0.0 ignores (it reads rows by name)."""
        jobs = {str(row[1]) for row in self._db.execute("PRAGMA table_info(jobs)")}
        if "input_path" not in jobs:
            # The file a job works on: a video whose audio it extracts.
            self._db.execute("ALTER TABLE jobs ADD COLUMN input_path TEXT NOT NULL DEFAULT ''")

    def _transaction(self) -> _Transaction:
        return _Transaction(self._db, self._lock)

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._db.execute(sql, tuple(params)).fetchall()]

    def _one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # ── Jobs ──────────────────────────────────────────────────────────────

    def add_job(self, url: str, source_kind: str, source_id: str, site: str, options: dict[str, Any],
                output_root: str, tab: str = "", title: str = "", thumbnail: str = "",
                items: list[dict[str, Any]] | None = None, account_id: int | None = None,
                subscription_id: int | None = None, state: str = "queued", not_before: float = 0.0,
                input_path: str = "") -> int:
        """Add a job at the end of the queue; returns its id.

        `input_path` is set for a job that works on a file on disk instead of downloading: a video
        whose audio it extracts (`url` is then the video's page, for its link).
        """
        now = time.time()
        with self._transaction() as db:
            top = db.execute("SELECT COALESCE(MAX(position), 0) FROM jobs").fetchone()[0]
            cursor = db.execute(
                "INSERT INTO jobs (url, source_kind, source_id, site, tab, title, thumbnail, options_json, output_root,"
                " input_path, account_id, subscription_id, state, position, not_before, items_total, created, updated)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, source_kind, source_id, site, tab, title, thumbnail, json.dumps(options), output_root,
                 input_path, account_id, subscription_id, state, top + 1, not_before, len(items or []), now, now))
            job_id = int(cursor.lastrowid or 0)
            if items:
                db.executemany(
                    "INSERT OR IGNORE INTO job_items (job_id, item_id, idx, title, duration) VALUES (?, ?, ?, ?, ?)",
                    [(job_id, str(item.get("id", "")), int(item.get("index", i + 1)), str(item.get("title") or ""),
                      float(item.get("duration") or 0)) for i, item in enumerate(items) if item.get("id")])
        return job_id

    def job(self, job_id: int) -> dict[str, Any] | None:
        """One job."""
        return self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def jobs(self, states: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Jobs in queue order, optionally only in some states."""
        if states is None:
            return self._rows("SELECT * FROM jobs ORDER BY position")
        wanted = tuple(states)
        marks = ",".join("?" * len(wanted))
        return self._rows(f"SELECT * FROM jobs WHERE state IN ({marks}) ORDER BY position", wanted)

    def update_job(self, job_id: int, **fields: Any) -> None:
        """Change some of a job's columns."""
        unknown = set(fields) - _JOB_FIELDS
        if unknown:
            raise ValueError(f"Unknown job fields: {sorted(unknown)}")
        if not fields:
            return
        fields["updated"] = time.time()
        columns = ", ".join(f"{name} = ?" for name in fields)
        with self._transaction() as db:
            db.execute(f"UPDATE jobs SET {columns} WHERE id = ?", (*fields.values(), job_id))

    def move_job(self, job_id: int, steps: int) -> None:
        """Move a job up (negative) or down (positive) among the queue's jobs."""
        with self._transaction() as db:
            order = [row[0] for row in db.execute("SELECT id FROM jobs ORDER BY position")]
            if job_id not in order:
                return
            index = order.index(job_id)
            target = max(0, min(len(order) - 1, index + steps))
            order.insert(target, order.pop(index))
            db.executemany("UPDATE jobs SET position = ? WHERE id = ?", [(i + 1, jid) for i, jid in enumerate(order)])

    def delete_jobs(self, job_ids: Iterable[int]) -> None:
        """Remove jobs (their items go with them); their files stay in the library under no job.

        SQLite gives a new job the next free number, which can be a removed job's, so a record still
        naming that job would pass for the new one's file (its Play button, Remove with its files).
        """
        ids = [(job_id,) for job_id in job_ids]
        with self._transaction() as db:
            db.executemany("UPDATE history SET job_id = NULL WHERE job_id = ?", ids)
            db.executemany("DELETE FROM jobs WHERE id = ?", ids)

    def recover(self) -> list[int]:
        """After a crash or restart, put jobs that were running back in the queue; returns their ids."""
        running = [row["id"] for row in self.jobs(("running", "retry_wait"))]
        with self._transaction() as db:
            db.execute("UPDATE jobs SET state = 'queued', updated = ? WHERE state IN ('running', 'retry_wait')",
                       (time.time(),))
        return running

    def job_items(self, job_id: int) -> list[dict[str, Any]]:
        """A job's selected playlist items in order."""
        return self._rows("SELECT * FROM job_items WHERE job_id = ? ORDER BY idx", (job_id,))

    def set_item_state(self, job_id: int, item_id: str, state: str, message: str = "") -> None:
        """Record one item's outcome."""
        with self._transaction() as db:
            db.execute("UPDATE job_items SET state = ?, message = ? WHERE job_id = ? AND item_id = ?",
                       (state, message, job_id, item_id))

    # ── History ───────────────────────────────────────────────────────────

    def last_file(self, job_id: int) -> str:
        """The newest file a download saved ("" when it saved none)."""
        row = self._one("SELECT filepath FROM history WHERE job_id = ? ORDER BY finished DESC, id DESC LIMIT 1",
                        (job_id,))
        return str(row["filepath"]) if row else ""

    def history_record(self, history_id: int) -> dict[str, Any] | None:
        """One library record."""
        return self._one("SELECT * FROM history WHERE id = ?", (history_id,))

    def history_for_job(self, job_id: int) -> list[dict[str, Any]]:
        """The library records of the files a download saved, oldest first."""
        return self._rows("SELECT * FROM history WHERE job_id = ? ORDER BY finished, id", (job_id,))

    def history_of_video(self, site: str, video_ids: Iterable[str], url: str) -> list[dict[str, Any]]:
        """Library records of one video (by its ID on the site, or its link), newest first."""
        ids = [video_id for video_id in video_ids if video_id]
        clauses, params = [], []
        if ids:
            clauses.append(f"(site = ? AND video_id IN ({', '.join('?' * len(ids))}))")
            params += [site, *ids]
        if url:
            clauses.append("url = ?")
            params.append(url)
        if not clauses:
            return []
        return self._rows(f"SELECT * FROM history WHERE {' OR '.join(clauses)} ORDER BY finished DESC, id DESC",
                          params)

    def history_for_path(self, filepath: str) -> dict[str, Any] | None:
        """The library record of a file, if it was downloaded here."""
        return self._one("SELECT * FROM history WHERE filepath = ?", (filepath,))

    # ── Playback ──────────────────────────────────────────────────────────

    def save_position(self, filepath: str, position: float, duration: float) -> None:
        """Remember where playback of a file stopped, in seconds."""
        with self._transaction() as db:
            db.execute("INSERT OR REPLACE INTO playback (filepath, position, duration, updated) VALUES (?, ?, ?, ?)",
                       (filepath, position, duration, time.time()))
            # Keep the newest MAX_POSITIONS; older ones are rarely resumed.
            db.execute("DELETE FROM playback WHERE filepath NOT IN "
                       "(SELECT filepath FROM playback ORDER BY updated DESC LIMIT ?)", (MAX_POSITIONS,))

    def position_for(self, filepath: str) -> float:
        """Where playback of a file stopped, in seconds (0 when it wasn't, or it finished)."""
        row = self._one("SELECT position FROM playback WHERE filepath = ?", (filepath,))
        return float(row["position"]) if row else 0.0

    def clear_position(self, filepath: str) -> None:
        """Forget a file's playback position (it played to the end)."""
        with self._transaction() as db:
            db.execute("DELETE FROM playback WHERE filepath = ?", (filepath,))

    def add_history(self, filepath: str, **fields: Any) -> int:
        """Record a finished file (replacing an older record of the same path)."""
        allowed = {"job_id", "video_id", "site", "kind", "title", "uploader", "url", "height", "duration", "size",
                   "thumbnail"}
        values = {key: value for key, value in fields.items() if key in allowed and value is not None}
        values["filepath"] = filepath
        values["finished"] = fields.get("finished") or time.time()
        columns = ", ".join(values)
        marks = ", ".join("?" * len(values))
        with self._transaction() as db:
            cursor = db.execute(f"INSERT OR REPLACE INTO history ({columns}) VALUES ({marks})", tuple(values.values()))
            return int(cursor.lastrowid or 0)

    def history(self, query: str = "", kind: str = "", site: str = "", offset: int = 0,
                limit: int = 100) -> list[dict[str, Any]]:
        """Finished files, newest first, filtered by text, type, and site."""
        where, params = self._history_filter(query, kind, site)
        return self._rows(f"SELECT * FROM history {where} ORDER BY finished DESC LIMIT ? OFFSET ?",
                          (*params, limit, offset))

    def history_count(self, query: str = "", kind: str = "", site: str = "") -> int:
        """How many finished files match the filters."""
        where, params = self._history_filter(query, kind, site)
        row = self._one(f"SELECT COUNT(*) AS n FROM history {where}", params)
        return int(row["n"]) if row else 0

    def history_sites(self) -> list[str]:
        """The sites in the library, for the filter."""
        return [row["site"] for row in self._rows("SELECT DISTINCT site FROM history WHERE site != '' ORDER BY site")]

    def delete_history(self, history_ids: Iterable[int]) -> None:
        """Remove records (the files stay)."""
        with self._transaction() as db:
            db.executemany("DELETE FROM history WHERE id = ?", [(item,) for item in history_ids])

    @staticmethod
    def _history_filter(query: str, kind: str, site: str) -> tuple[str, list[Any]]:
        clauses, params = [], []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(title LIKE ? ESCAPE '\\' OR uploader LIKE ? ESCAPE '\\' OR filepath LIKE ? ESCAPE '\\')")
            params += [f"%{escaped}%"] * 3
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if site:
            clauses.append("site = ?")
            params.append(site)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    # ── Subscriptions ─────────────────────────────────────────────────────

    def add_subscription(self, url: str, title: str, site: str, options: dict[str, Any], output_root: str,
                         interval_hours: int, auto_download: bool, account_id: int | None,
                         next_check: float) -> int:
        """Watch a channel or playlist; returns the id (an existing subscription keeps its id)."""
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO subscriptions (url, title, site, options_json, output_root, interval_hours,"
                " auto_download, account_id, next_check, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, title, site, json.dumps(options), output_root, interval_hours, int(auto_download), account_id,
                 next_check, time.time()))
            return int(db.execute("SELECT id FROM subscriptions WHERE url = ?", (url,)).fetchone()[0])

    def subscriptions(self) -> list[dict[str, Any]]:
        """Every subscription, by title."""
        return self._rows("SELECT * FROM subscriptions ORDER BY title COLLATE NOCASE")

    def subscription(self, sub_id: int) -> dict[str, Any] | None:
        """One subscription."""
        return self._one("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))

    def due_subscriptions(self, now: float) -> list[dict[str, Any]]:
        """Enabled subscriptions whose next check time has come, longest overdue first."""
        return self._rows("SELECT * FROM subscriptions WHERE enabled = 1 AND next_check <= ? ORDER BY next_check",
                          (now,))

    def update_subscription(self, sub_id: int, **fields: Any) -> None:
        """Change some of a subscription's columns."""
        unknown = set(fields) - _SUB_FIELDS
        if unknown:
            raise ValueError(f"Unknown subscription fields: {sorted(unknown)}")
        if fields:
            columns = ", ".join(f"{name} = ?" for name in fields)
            with self._transaction() as db:
                db.execute(f"UPDATE subscriptions SET {columns} WHERE id = ?", (*fields.values(), sub_id))

    def delete_subscription(self, sub_id: int) -> None:
        """Stop watching (downloaded files and the archive stay)."""
        with self._transaction() as db:
            db.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))

    def seen(self, sub_id: int) -> dict[str, str]:
        """Items a subscription already queued or skipped: {video id: status}."""
        return {row["video_id"]: row["status"]
                for row in self._rows("SELECT video_id, status FROM subscription_seen WHERE sub_id = ?", (sub_id,))}

    def mark_seen(self, sub_id: int, video_ids: Iterable[str], status: str) -> None:
        """Remember items so later checks don't queue them again."""
        with self._transaction() as db:
            db.executemany("INSERT OR REPLACE INTO subscription_seen (sub_id, video_id, status) VALUES (?, ?, ?)",
                           [(sub_id, video_id, status) for video_id in video_ids])

    # ── Sign-in records (no secrets) ──────────────────────────────────────

    def save_account(self, site: str, label: str, method: str, domains: list[str], browser: str = "",
                     expires: float = 0.0) -> int:
        """Create or replace the sign-in record for a site; returns its id."""
        now = time.time()
        with self._transaction() as db:
            existing = db.execute("SELECT id, created FROM accounts WHERE site = ?", (site,)).fetchone()
            if existing:
                db.execute("UPDATE accounts SET label = ?, method = ?, browser = ?, domains_json = ?, status = 'ok',"
                           " refreshed = ?, expires = ? WHERE id = ?",
                           (label, method, browser, json.dumps(domains), now, expires, existing[0]))
                return int(existing[0])
            cursor = db.execute(
                "INSERT INTO accounts (site, label, method, browser, domains_json, created, refreshed, expires)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (site, label, method, browser, json.dumps(domains), now, now, expires))
            return int(cursor.lastrowid or 0)

    def accounts(self) -> list[dict[str, Any]]:
        """Every sign-in record."""
        return self._rows("SELECT * FROM accounts ORDER BY label COLLATE NOCASE")

    def account(self, account_id: int) -> dict[str, Any] | None:
        """One sign-in record."""
        return self._one("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def account_for_site(self, site: str) -> dict[str, Any] | None:
        """The sign-in record for a site key, if any."""
        return self._one("SELECT * FROM accounts WHERE site = ?", (site,))

    def update_account(self, account_id: int, **fields: Any) -> None:
        """Change some of a sign-in record's columns."""
        unknown = set(fields) - _ACCOUNT_FIELDS
        if unknown:
            raise ValueError(f"Unknown account fields: {sorted(unknown)}")
        if fields:
            columns = ", ".join(f"{name} = ?" for name in fields)
            with self._transaction() as db:
                db.execute(f"UPDATE accounts SET {columns} WHERE id = ?", (*fields.values(), account_id))

    def delete_account(self, account_id: int) -> None:
        """Forget a sign-in record; jobs that used it keep running without it."""
        with self._transaction() as db:
            db.execute("UPDATE jobs SET account_id = NULL WHERE account_id = ?", (account_id,))
            db.execute("UPDATE subscriptions SET account_id = NULL WHERE account_id = ?", (account_id,))
            db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


class _Transaction:
    """BEGIN IMMEDIATE ... COMMIT under the store's lock, rolled back on an exception."""

    def __init__(self, db: sqlite3.Connection, lock: threading.RLock) -> None:
        self._db = db
        self._lock = lock

    def __enter__(self) -> sqlite3.Connection:
        self._lock.acquire()
        try:
            self._db.execute("BEGIN IMMEDIATE")
        except BaseException:
            self._lock.release()
            raise
        return self._db

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, trace: Any) -> None:
        try:
            self._db.execute("ROLLBACK" if kind is not None else "COMMIT")
        finally:
            self._lock.release()
