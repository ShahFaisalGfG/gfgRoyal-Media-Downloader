import gc
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test session (QObject controllers and models need it).

    Imported here, not at module level, so the engine and command-line tests run without PySide6.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    # Let queued deletions and finished worker signals run, and free Qt objects while the
    # application still exists, so nothing is torn down during interpreter shutdown.
    app.processEvents()
    gc.collect()
    app.processEvents()


@pytest.fixture(autouse=True)
def isolated_data(tmp_path_factory, monkeypatch):
    """Point settings, logs, the library, and tools at temp folders, never the real data folders.

    They get folders of their own, so a test's tmp_path starts empty.
    """
    from gfgmd.utils import paths, settings
    data = tmp_path_factory.mktemp("data")
    local = tmp_path_factory.mktemp("local")
    monkeypatch.setattr(paths, "_data_dir", str(data))
    monkeypatch.setattr(paths, "_local_dir", str(local))
    monkeypatch.setattr(settings, "_cache", None, raising=False)
    monkeypatch.setattr(settings, "_read_error", False, raising=False)
    yield data


@pytest.fixture
def fake_ytdlp(tmp_path):
    """A command prefix that runs tests/fakes/fake_ytdlp.py in place of yt-dlp."""
    state = tmp_path / "fake-state"
    state.mkdir()
    return [sys.executable, str(FAKES / "fake_ytdlp.py"), "--fake-state", str(state)]
