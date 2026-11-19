# self_test.py - checks that a build runs its engine, opens its database, and loads every QML module
#
# PyInstaller only follows static imports and the bundle's QtQml hook trims Qt modules, so a build
# can succeed and still fail on a user's machine (a trimmed QML plugin, a missing Qt module). The
# release workflow runs the frozen exe with --self-test so a missing piece fails the build instead.
# Nothing here downloads anything or changes the user's data.

import os
import re
import sys
import traceback
from pathlib import Path
from typing import Callable, Optional

from gfgmd.utils.console import safe_print
from gfgmd.utils.helpers import resource_path

Check = tuple[str, Callable[[], None]]

_QML_DIR = "gfgmd/qml"
_qt_app: Optional[object] = None


def _check_engine() -> None:
    """The download engine builds a hardened yt-dlp command and parses its progress lines."""
    from gfgmd.core.command import RunPaths, download_command
    from gfgmd.core.options import DownloadOptions
    from gfgmd.core.progress import ProgressTracker
    from gfgmd.core.sources import source_from_url
    from gfgmd.core.tools import ToolSet

    url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    root = Path("C:/self-test")
    command = download_command(url, source_from_url(url), DownloadOptions(), ToolSet("y", "f", "p", "d"),
                               RunPaths(root, root / "a.txt", root / "j", root / "c"))
    if "--ignore-config" not in command or command[-2:] != ["--", url]:
        raise RuntimeError("the yt-dlp command is not hardened")
    tracker = ProgressTracker()
    tracker.feed("out", '@@gfgr:item {"id":"x","title":"T"}')
    if tracker.snapshot().title != "T":
        raise RuntimeError("progress lines are not parsed")


def _check_database() -> None:
    """The library database opens (SQLite with WAL) in a temporary folder."""
    import tempfile

    from gfgmd.core.store import Store

    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / "library.db")
        try:
            store.add_job("https://example.com/v", "generic", "x", "example.com", {}, folder)
            if len(store.jobs()) != 1:
                raise RuntimeError("the queue didn't store a job")
        finally:
            store.close()


def _qml_files() -> list[str]:
    """Every bundled .qml file."""
    root = resource_path(_QML_DIR)
    files = [os.path.join(folder, name)
             for folder, _dirs, names in os.walk(root)
             for name in names if name.endswith(".qml")]
    if not files:
        raise RuntimeError(f"no QML files found in {root}")
    return sorted(files)


def _check_qml() -> None:
    """Compile every bundled QML file, resolving each Qt module and component it imports."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtWidgets import QApplication

    global _qt_app
    _qt_app = QApplication.instance() or QApplication([sys.argv[0]])
    engine = QQmlEngine()
    engine.addImportPath(resource_path(_QML_DIR))
    errors: list[str] = []
    for path in _qml_files():
        component = QQmlComponent(engine, QUrl.fromLocalFile(path))
        if component.isError():
            errors.extend(error.toString() for error in component.errors())
    if errors:
        raise RuntimeError("; ".join(errors))


def _check_images() -> None:
    """Every image the app shows is bundled; QML shows a missing image as a blank, not an error."""
    from gfgmd.app import SPLASH_LOGO, WINDOW_ICONS

    missing = [path for path in (SPLASH_LOGO, *WINDOW_ICONS.values()) if not os.path.isfile(resource_path(path))]
    for qml in _qml_files():
        with open(qml, encoding="utf-8") as fh:
            for source in re.findall(r'source:\s*"([^"]+\.(?:png|ico|svg))"', fh.read()):
                if not os.path.isfile(os.path.join(os.path.dirname(qml), source)):
                    missing.append(f"{source} (from {os.path.basename(qml)})")
    if missing:
        raise RuntimeError("missing images: " + ", ".join(missing))


def _check_media() -> None:
    """The players can work: Qt Multimedia loads its FFmpeg backend and reads a short sound."""
    import os
    import struct
    import tempfile
    import wave

    from PySide6.QtCore import QCoreApplication, QElapsedTimer, QUrl
    from PySide6.QtMultimedia import QMediaPlayer

    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
    with tempfile.TemporaryDirectory(prefix="gfgmd-media-") as folder:
        sample = os.path.join(folder, "tone.wav")
        with wave.open(sample, "wb") as tone:
            tone.setnchannels(1)
            tone.setsampwidth(2)
            tone.setframerate(8000)
            tone.writeframes(b"".join(struct.pack("<h", 0) for _ in range(800)))
        player = QMediaPlayer()
        player.setSource(QUrl.fromLocalFile(sample))
        timer = QElapsedTimer()
        timer.start()
        loaded = (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        while player.mediaStatus() not in loaded and player.error() == QMediaPlayer.Error.NoError \
                and timer.elapsed() < 10000:
            QCoreApplication.processEvents()
        status, error = player.mediaStatus(), player.errorString()
        player.setSource(QUrl())
        if status not in loaded:
            raise RuntimeError(f"the media backend couldn't open a sound file: {error or status.name}")


def _check_updates() -> None:
    """The updater can work: HTTPS with Windows' trusted root certificates, and every signing key reads."""
    import ssl

    from gfgmd.config.defaults import UpdateInfo
    from gfgmd.utils import signature

    if not ssl.create_default_context().cert_store_stats().get("x509_ca"):
        raise RuntimeError("no trusted root certificates were loaded")
    for pem in UpdateInfo.PUBLIC_KEYS:
        signature.public_point(pem)


CHECKS: list[Check] = [
    ("Download engine", _check_engine),
    ("Library database", _check_database),
    ("QML", _check_qml),
    ("Images", _check_images),
    ("Players", _check_media),
    ("Updates", _check_updates),
]


def run_self_test(report_path: Optional[str] = None, checks: Optional[list[Check]] = None) -> int:
    """Run every check, write a PASS/FAIL report, and return 0 when all pass, else 1."""
    selected = CHECKS if checks is None else checks
    lines: list[str] = []
    failed = 0
    for name, check in selected:
        try:
            check()
            lines.append(f"PASS  {name}")
        except Exception as error:
            failed += 1
            lines.append(f"FAIL  {name}: {error!r}")
            lines.extend("      " + line for line in traceback.format_exc().rstrip().splitlines())
    lines.append(f"{failed} of {len(selected)} checks failed" if failed else f"All {len(selected)} checks passed")
    report = "\n".join(lines) + "\n"
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(report)
    if sys.stdout is not None:
        safe_print(report.rstrip("\n"))
    return 1 if failed else 0
