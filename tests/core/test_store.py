"""The library database: queue order, recovery, history search, subscriptions, and sign-in records."""

import sqlite3
from pathlib import Path

import pytest

from gfgmd.core.store import SCHEMA_VERSION, Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = Store(tmp_path / "library.db")
    yield db
    db.close()


def add(store: Store, title: str, **kwargs) -> int:
    return store.add_job(f"https://youtu.be/{title}", "video", title, "youtube", {"kind": "video"}, "C:/D",
                         title=title, **kwargs)


def test_queue_order_and_moves(store: Store) -> None:
    a, b, c = add(store, "a"), add(store, "b"), add(store, "c")
    assert [job["id"] for job in store.jobs()] == [a, b, c]
    store.move_job(c, -2)
    assert [job["id"] for job in store.jobs()] == [c, a, b]
    store.move_job(c, 10)
    assert [job["id"] for job in store.jobs()] == [a, b, c]


def test_items_and_states(store: Store) -> None:
    job = add(store, "p", items=[{"id": "x", "title": "X"}, {"id": "y", "title": "Y", "index": 5}])
    assert [item["item_id"] for item in store.job_items(job)] == ["x", "y"]
    assert store.job(job)["items_total"] == 2
    store.set_item_state(job, "y", "skipped", "Private video")
    assert store.job_items(job)[1]["state"] == "skipped"
    store.delete_jobs([job])
    assert store.job_items(job) == []


def test_recover_requeues_running_jobs(store: Store) -> None:
    a, b = add(store, "a"), add(store, "b")
    store.update_job(a, state="running")
    store.update_job(b, state="paused")
    assert store.recover() == [a]
    assert [job["state"] for job in store.jobs()] == ["queued", "paused"]


def test_update_rejects_unknown_columns(store: Store) -> None:
    with pytest.raises(ValueError):
        store.update_job(add(store, "a"), id=5)


def test_history_search_and_paging(store: Store) -> None:
    for i in range(30):
        store.add_history(f"C:/D/clip_{i}%.mp4", title=f"Clip {i}", site="youtube" if i % 2 else "vimeo",
                          kind="audio" if i % 3 == 0 else "video", finished=1000 + i)
    assert store.history_count() == 30
    assert [row["title"] for row in store.history(limit=2)] == ["Clip 29", "Clip 28"]
    assert store.history_count(query="Clip 1") == 11  # 1, 10-19
    assert store.history_count(query="%") == 30  # a literal percent sign, not a wildcard
    assert store.history_count(query="_") == 30
    assert store.history_count(site="vimeo", kind="audio") == 5
    assert store.history_sites() == ["vimeo", "youtube"]
    first = store.history(limit=1)[0]
    store.delete_history([first["id"]])
    assert store.history_count() == 29


def test_subscriptions_and_seen(store: Store) -> None:
    sub = store.add_subscription("https://www.youtube.com/@x/videos", "X", "youtube", {}, "C:/D", 6, True, None, 50)
    assert store.add_subscription("https://www.youtube.com/@x/videos", "X", "youtube", {}, "C:/D", 6, True, None,
                                  50) == sub
    assert [row["id"] for row in store.due_subscriptions(100)] == [sub]
    store.update_subscription(sub, next_check=200)
    assert store.due_subscriptions(100) == []
    store.mark_seen(sub, ["a", "b"], "queued")
    store.mark_seen(sub, ["b"], "skipped")
    assert store.seen(sub) == {"a": "queued", "b": "skipped"}


def test_accounts_replace_and_delete(store: Store) -> None:
    first = store.save_account("youtube", "YouTube", "browser", [".youtube.com"])
    assert store.save_account("youtube", "YouTube", "file", [".youtube.com"]) == first
    assert store.account(first)["method"] == "file"
    job = add(store, "a", account_id=first)
    store.delete_account(first)
    assert store.account(first) is None and store.job(job)["account_id"] is None


def test_reopen_keeps_data(tmp_path: Path) -> None:
    db = Store(tmp_path / "library.db")
    add(db, "a")
    db.close()
    again = Store(tmp_path / "library.db")
    assert len(again.jobs()) == 1
    again.close()


def test_a_1_0_0_library_gains_the_jobs_input_file_and_stays_readable(tmp_path: Path) -> None:
    """The new column is added in place, and the layout number 1.0.0 checks stays 2, so it still opens."""
    db = Store(tmp_path / "library.db")
    add(db, "a")
    db.close()
    raw = sqlite3.connect(tmp_path / "library.db")
    raw.execute("ALTER TABLE jobs DROP COLUMN input_path")  # as 1.0.0 left it
    raw.commit()
    raw.close()
    again = Store(tmp_path / "library.db")
    try:
        assert [job["input_path"] for job in again.jobs()] == [""]
        job = add(again, "b", input_path="C:/Videos/b.mp4")
        assert again.job(job)["input_path"] == "C:/Videos/b.mp4"
    finally:
        again.close()
    raw = sqlite3.connect(tmp_path / "library.db")
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
    # 1.0.0 inserts by column name; the new column fills in its default.
    raw.execute("INSERT INTO jobs (url, source_kind, source_id, site, options_json, output_root, state, position,"
                " created, updated) VALUES ('u', 'video', 'c', 'youtube', '{}', 'C:/D', 'queued', 9, 0, 0)")
    assert raw.execute("SELECT input_path FROM jobs WHERE source_id = 'c'").fetchone()[0] == ""
    raw.close()
