# boot_thread.py - import the controllers off the GUI thread, reporting staged splash progress
#
# The imports inside run() are a deliberate exception to the top-of-file import rule: Python
# resolves a file's top-level imports before anything else runs in it, so showing progress while
# the modules load is only possible when they are imported after the splash is visible, here, off
# the GUI thread.

import traceback

from PySide6.QtCore import QThread, Signal


class BootThread(QThread):
    """Imports the engine and controllers, staged for splash progress."""

    stage_changed = Signal(str, int)
    boot_ready = Signal()
    boot_failed = Signal(str)  # what went wrong, with the traceback, for the log

    def run(self) -> None:
        """Load the download engine and the controllers, then signal that the window can be built."""
        try:
            self.stage_changed.emit("Starting up...", 35)
            import gfgmd.core.jobs  # noqa: F401
            import gfgmd.core.analyze  # noqa: F401
            import gfgmd.core.store  # noqa: F401

            self.stage_changed.emit("Almost ready...", 75)
            import gfgmd.controllers.app_ctrl  # noqa: F401
            import gfgmd.controllers.prefs_ctrl  # noqa: F401
            import gfgmd.controllers.queue_ctrl  # noqa: F401
            import gfgmd.controllers.analyze_ctrl  # noqa: F401
            import gfgmd.controllers.library_ctrl  # noqa: F401
            import gfgmd.controllers.subscriptions_ctrl  # noqa: F401
            import gfgmd.controllers.signins_ctrl  # noqa: F401
            import gfgmd.controllers.tools_ctrl  # noqa: F401
            import gfgmd.controllers.update_ctrl  # noqa: F401

            self.boot_ready.emit()
        except Exception:  # reported (and logged) by the window's start-up, which quits
            self.boot_failed.emit(f"Loading the app's modules failed:\n{traceback.format_exc().rstrip()}")
