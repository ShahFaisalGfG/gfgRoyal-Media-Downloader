# tasks.py - run blocking work on a thread pool and deliver results on the GUI thread
#
# Controllers hand a function to TaskRunner.start(); it runs on the runner's pool and its result
# (or error) arrives through the runner's own slots, which live on the GUI thread, before the
# callback is called. Callbacks are therefore always safe to touch Qt objects and models.

from __future__ import annotations

import itertools
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot

from gfgmd.utils.logging import write_log


class _Signals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)


class _Task(QRunnable):
    """One function call on the pool; the runner keeps it alive until its signal is delivered."""

    def __init__(self, task_id: int, fn: Callable[..., Any], args: tuple[Any, ...]) -> None:
        super().__init__()
        # The runner owns the task until its result is delivered; the pool must not delete it from
        # under the queued signal that carries the result back.
        self.setAutoDelete(False)
        self.task_id = task_id
        self.signals = _Signals()
        self._fn = fn
        self._args = args

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as error:  # the boundary of background work: report every failure
            write_log(f"Background task failed: {error}\n{traceback.format_exc()}", "critical")
            try:
                self.signals.failed.emit(self.task_id, str(error) or type(error).__name__)
            except RuntimeError:
                pass  # the app is shutting down
            return
        try:
            self.signals.done.emit(self.task_id, result)
        except RuntimeError:
            pass


class TaskRunner(QObject):
    """A thread pool whose results come back on the GUI thread."""

    def __init__(self, threads: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(threads, 1))
        self._ids = itertools.count(1)
        self._live: dict[int, tuple[_Task, Callable[[Any], None] | None, Callable[[str], None] | None]] = {}

    @property
    def active(self) -> int:
        """How many tasks are queued or running."""
        return len(self._live)

    def set_threads(self, threads: int) -> None:
        """Change how many tasks run at once."""
        self._pool.setMaxThreadCount(max(threads, 1))

    def start(self, fn: Callable[..., Any], *args: Any, on_done: Callable[[Any], None] | None = None,
              on_error: Callable[[str], None] | None = None) -> int:
        """Queue fn(*args); returns the task id."""
        task_id = next(self._ids)
        task = _Task(task_id, fn, args)
        task.signals.done.connect(self._done, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        self._live[task_id] = (task, on_done, on_error)
        self._pool.start(task)
        return task_id

    @Slot(int, object)
    def _done(self, task_id: int, result: object) -> None:
        entry = self._live.pop(task_id, None)
        if entry is not None and entry[1] is not None:
            entry[1](result)

    @Slot(int, str)
    def _failed(self, task_id: int, message: str) -> None:
        entry = self._live.pop(task_id, None)
        if entry is not None and entry[2] is not None:
            entry[2](message)

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """Drop queued tasks and wait briefly for running ones."""
        self._pool.clear()
        self._pool.waitForDone(timeout_ms)
