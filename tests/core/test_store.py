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


def test_a_removed_jobs_files_stay_in_the_library_under_no_job(store: Store) -> None:
    """A new job may get a removed job's number; the old files must not pass for the new job's."""
    job = add(store, "a")
    store.add_history("C:/V/a.mp4", job_id=job, title="a")
    store.delete_jobs([job])
    assert store.history()[0]["job_id"] is None
    reused = add(store, "b")
    assert store.history_for_job(reused) == [] and store.last_file(reused) == ""


def test_records_naming_jobs_removed_earlier_are_released_on_open(tmp_path: Path) -> None:
    db = Store(tmp_path / "library.db")
    db.add_history("C:/V/old.mp4", job_id=7, title="old")  # as 1.0.0 left them after Clear finished
    db.close()
    again = Store(tmp_path / "library.db")
    try:
        assert again.history()[0]["job_id"] is None
    finally:
        again.close()


def test_listed_videos_fill_in_and_keep_their_state(store: Store) -> None:
    """A playlist's list arrives on every attempt: new videos are added, known ones keep their state."""
    job = add(store, "p", items=[{"id": "x", "title": "X", "index": 1}])
    store.set_item_state(job, "x", "done")
    store.add_items(job, [{"id": "x", "title": "Renamed", "index": 1, "url": "https://youtu.be/x", "thumbnail": "t.jpg"},
                          {"id": "y", "title": "Y", "index": 2, "duration": 61}])
    items = store.job_items(job)
    assert [(i["item_id"], i["title"], i["state"], i["url"], i["thumbnail"]) for i in items] == [
        ("x", "X", "done", "https://youtu.be/x", "t.jpg"), ("y", "Y", "pending", "", "")]
    assert store.job(job)["items_total"] == 2


def test_item_states_in_bulk(store: Store) -> None:
    job = add(store, "p", items=[{"id": "x", "title": "X"}, {"id": "y", "title": "Y"}])
    store.set_item_state(job, "x", "done")
    # A later attempt's archive check names a video this run saved; it stays saved.
    store.set_item_states(job, [("x", "archived", ""), ("y", "deferred", "No answer"), ("z", "done", "")])
    assert {i["item_id"]: i["state"] for i in store.job_items(job)} == {"x": "done", "y": "deferred", "z": "done"}
    # So does one whose earlier "waiting again" reaches the store after its file did.
    store.set_item_states(job, [("z", "pending", ""), ("z", "failed", "Dropped")])
    assert {i["item_id"]: i["state"] for i in store.job_items(job)}["z"] == "done"
    assert store.job_items(job)[-1]["idx"] == 3 and store.job(job)["items_total"] == 3
    assert store.item_counts(job) == {"done": 2, "deferred": 1}
    store.reset_items(job, ("deferred", "failed"))
    assert store.item_counts(job) == {"done": 2, "pending": 1}
    store.drop_item(job, "y")
    assert [i["item_id"] for i in store.job_items(job)] == ["x", "z"] and store.job(job)["items_total"] == 2


def test_new_columns_reach_a_library_made_before_them(tmp_path: Path) -> None:
    """Folder, batch, song links, Library groups, and kept uploads are added in place, with their
    lookup indexes, without a new layout number."""
    db = Store(tmp_path / "library.db")
    add(db, "a")
    db.add_history("C:/D/a.mp4", title="a")
    db.close()
    raw = sqlite3.connect(tmp_path / "library.db")
    for index in ("history_by_job", "history_by_group", "history_by_video"):
        raw.execute(f"DROP INDEX {index}")
    for table, column in (("jobs", "folder"), ("jobs", "batch"), ("job_items", "url"), ("job_items", "thumbnail"),
                          ("history", "group_key"), ("history", "group_title"), ("history", "position"),
                          ("history", "output_root"), ("subscription_seen", "url"), ("subscription_seen", "title")):
        raw.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    raw.commit()
    raw.close()
    again = Store(tmp_path / "library.db")
    try:
        record = again.history()[0]
        assert record["group_key"] is None and record["position"] == 0  # to be worked out by the Library
        assert record["output_root"] == ""  # not known for a file saved before it was recorded
        again.add_history("C:/D/List/b.mp4", title="b", output_root="C:/D")
        assert again.history_for_path("C:/D/List/b.mp4")["output_root"] == "C:/D"
        job = add(again, "b", folder="Mix", batch=True, items=[{"id": "q", "url": "https://youtu.be/q"}])
        assert (again.job(job)["folder"], again.job(job)["batch"]) == ("Mix", 1)
        assert again.job_items(job)[0]["url"] == "https://youtu.be/q"
        indexes = {row["name"] for row in again._rows("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {"history_by_job", "history_by_group", "history_by_video"} <= indexes
    finally:
        again.close()


def test_uploads_kept_for_download_new_keep_their_links(tmp_path: Path) -> None:
    """Pending uploads hold their own link and title; marking them queued leaves the pending list."""
    db = Store(tmp_path / "library.db")
    try:
        sub = db.add_subscription("https://soundcloud.com/artist", "Artist", "soundcloud", {}, "C:/D", 6, False, None, 0.0)
        db.mark_pending(sub, [{"id": "123", "url": "https://soundcloud.com/artist/song", "title": "Song"}])
        assert db.pending_uploads(sub) == [{"id": "123", "url": "https://soundcloud.com/artist/song", "title": "Song"}]
        db.mark_seen(sub, ["123"], "queued")
        assert db.pending_uploads(sub) == [] and db.seen(sub) == {"123": "queued"}
    finally:
        db.close()


def test_many_video_ids_are_looked_up_in_parts(tmp_path: Path) -> None:
    """A channel's thousands of IDs stay under SQLite's limit on query values."""
    db = Store(tmp_path / "library.db")
    try:
        db.add_history("C:/D/a.mp4", title="a", video_id="v1199", site="youtube")
        ids = [f"v{number}" for number in range(40000)]
        assert [row["video_id"] for row in db.history_of_video("youtube", ids, "")] == ["v1199"]
    finally:
        db.close()


def test_a_videos_place_in_its_list(tmp_path: Path) -> None:
    db = Store(tmp_path / "library.db")
    try:
        job = add(db, "a", items=[{"id": "x"}, {"id": "y"}, {"id": "z"}])
        assert [db.item_number(job, item) for item in ("x", "z", "missing")] == [1, 3, 0]
    finally:
        db.close()
