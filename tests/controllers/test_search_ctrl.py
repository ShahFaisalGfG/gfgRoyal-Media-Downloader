"""Search from the link box: results arrive in a list, songs get their artist, repeats come from memory."""

import time
from pathlib import Path

import pytest

from gfgmd.controllers.search_ctrl import SearchController
from gfgmd.core.runner import run_to_completion
from gfgmd.core.tools import ToolSet
from gfgmd.services.context import AppContext

TOOLS = ToolSet("FAKE-YT-DLP", "ffmpeg", "ffprobe", "deno")


@pytest.fixture
def context(tmp_path: Path, monkeypatch) -> AppContext:
    context = AppContext(tmp_path / "local")
    monkeypatch.setattr(context, "tools", lambda: TOOLS)
    return context


def wait_for(qapp, condition, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make(qapp, context, fake_ytdlp):
    made: list[SearchController] = []
    runs: list[list[str]] = []

    def runner(command, on_line, stop):
        runs.append(command)
        return run_to_completion(fake_ytdlp + command[1:], on_line, stop)

    def build(fetch=None) -> tuple[SearchController, list[list[str]]]:
        controller = SearchController(context, quick_fetch=fetch, runner=runner)
        made.append(controller)
        return controller, runs

    yield build
    for controller in made:
        controller.shutdown()


def rows(controller: SearchController) -> list[dict]:
    return controller.model.rows()


def test_results_list_with_their_details_and_ticked_ones_download_together(qapp, make):
    search, runs = make()
    search.search("  lofi   beats ", False)
    assert search.shown and search.query == "lofi beats"
    assert wait_for(qapp, lambda: not search.busy and len(rows(search)) == 3)
    first = rows(search)[0]
    assert first["detail"] == "Some Channel  ·  4:05  ·  1.2M views" and first["thumbnail"].endswith("hq720.jpg")
    assert rows(search)[2]["live"] is True
    search.setChecked("sssssssss02", True)
    search.setChecked("sssssssss01", True)
    assert search.checkedCount == 2
    assert search.checkedLinks() == ["https://www.youtube.com/watch?v=sssssssss01",
                                     "https://www.youtube.com/watch?v=sssssssss02"]
    # The same words again come from memory: no second run, and the ticks stay as they were.
    search.search("lofi beats", False)
    assert len(runs) == 1 and search.checkedCount == 2
    search.close()
    assert not search.shown and rows(search) == [] and search.query == ""
    search.search("lofi beats", False)  # shown again from memory after closing
    assert wait_for(qapp, lambda: len(rows(search)) == 3) and len(runs) == 1


def test_songs_come_from_youtube_music_and_get_their_artist(qapp, make):
    asked: list[str] = []

    def fetch(url):
        asked.append(url)
        return {"title": "Song", "author_name": "Ali Sethi - Topic"}

    search, runs = make(fetch)
    search.search("pasoori", True)
    assert wait_for(qapp, lambda: not search.busy and len(rows(search)) == 3)
    assert runs[0][-1] == "https://music.youtube.com/search?q=pasoori#songs"
    assert wait_for(qapp, lambda: rows(search)[1]["detail"].startswith("Ali Sethi"))
    assert rows(search)[0]["url"] == "https://music.youtube.com/watch?v=sssssssss01"


def test_a_failed_search_says_so_and_more_results_ask_for_more(qapp, make):
    search, runs = make()
    search.search("fail", False)
    assert wait_for(qapp, lambda: not search.busy)
    assert search.error.startswith("The search couldn't be run") and rows(search) == []
    search.search("plenty", False)
    assert wait_for(qapp, lambda: not search.busy and len(rows(search)) == 3)
    assert not search.canMore  # three results, fewer than the first page asked for
