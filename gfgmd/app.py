# app.py - application entry point: QApplication + QQmlApplicationEngine, tray, and launch hand-off

from __future__ import annotations

import os
import sys
from typing import Any, Optional, cast

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from gfgmd.config.defaults import AppInfo
from gfgmd.core.lyrics import fetch_json
from gfgmd.core.sources import likely_media
from gfgmd.services import autostart
from gfgmd.services.companion import cookies_from_extension
from gfgmd.ui.boot_thread import BootThread
from gfgmd.ui.splash_screen import SplashScreen
from gfgmd.utils.helpers import resource_path
from gfgmd.utils.logging import write_log
from gfgmd.utils.self_test import run_self_test
from gfgmd.utils.settings import load_settings
from gfgmd.utils.single_instance import LaunchRequest, SingleInstance, hold_app_mutexes

_SELF_TEST_FLAG = "--self-test"
_LINKS_MODE = "links"
_SIGNIN_MODE = "signin"
# Images loaded outside QML; the self-test checks they are bundled.
SPLASH_LOGO = "gfgmd/assets/icons/Square310x310Logo.scale-100.png"
WINDOW_ICONS = {size: f"gfgmd/assets/icons/Square44x44Logo.targetsize-{size}.png" for size in (16, 32, 48, 256)}


def _links_in(arguments: list[str]) -> list[str]:
    """Web links given on the command line (a browser or a shortcut can pass them)."""
    return [arg for arg in arguments if arg.startswith(("https://", "http://"))]


class _Startup:
    """Owns the splash and boot thread, then builds the window, tray, and controllers."""

    def __init__(self, app: QApplication, instance: SingleInstance, background: bool, links: list[str]) -> None:
        self._app = app
        self._instance = instance
        self._background = background
        self._links = links
        self._engine: Optional[QQmlApplicationEngine] = None
        self._controllers: dict[str, Any] = {}
        self._context: Any = None
        self._tray: Optional[QSystemTrayIcon] = None
        self._tray_menu: Optional[QMenu] = None
        self._root: Optional[QWindow] = None
        self._applied: dict[str, Any] = {}
        self._last_clipboard = ""

        self._splash = SplashScreen(resource_path(SPLASH_LOGO))
        if not background:
            self._splash.show()
        self._boot = BootThread()
        self._boot.stage_changed.connect(self._splash.set_stage)
        self._boot.boot_ready.connect(self._on_ready)
        self._boot.boot_failed.connect(self._on_failed)
        self._boot.start()

    def _on_ready(self) -> None:
        """Build the controllers, window, and tray once boot has finished."""
        try:
            from gfgmd.controllers.analyze_ctrl import AnalyzeController
            from gfgmd.controllers.app_ctrl import AppController
            from gfgmd.controllers.library_ctrl import LibraryController
            from gfgmd.controllers.player_ctrl import PlayerController
            from gfgmd.controllers.prefs_ctrl import PrefsController
            from gfgmd.controllers.queue_ctrl import QueueController
            from gfgmd.controllers.signins_ctrl import SignInsController
            from gfgmd.controllers.subscriptions_ctrl import SubscriptionsController
            from gfgmd.controllers.tools_ctrl import ToolsController
            from gfgmd.controllers.update_ctrl import UpdateController
            from gfgmd.services.context import AppContext
            from gfgmd.services.notifier import Notifier
            from gfgmd.services.thumbnails import ThumbnailCache
            from gfgmd.services.tool_manager import ToolManager

            self._app.setWindowIcon(_load_icon())
            context = AppContext()
            manager = ToolManager(context)
            app_ctrl = AppController()
            notifier = Notifier(self._show_window, app_ctrl.revealFile)
            prefs_ctrl = PrefsController(context)
            tools_ctrl = ToolsController(manager)
            queue_ctrl = QueueController(context, manager, notifier, lyrics_fetch=fetch_json)
            analyze_ctrl = AnalyzeController(context, queue_ctrl)
            library_ctrl = LibraryController(context)
            subs_ctrl = SubscriptionsController(context, queue_ctrl, notifier)
            signins_ctrl = SignInsController(context)
            player_ctrl = PlayerController(context)
            update_ctrl = UpdateController(_update_config())
            update_ctrl.set_busy_sources([queue_ctrl])
            thumbnails = ThumbnailCache(context.thumbnails_dir)

            prefs_ctrl.settingsChanged.connect(update_ctrl.preferencesChanged)
            prefs_ctrl.settingsChanged.connect(self._apply_preferences)
            queue_ctrl.fileSaved.connect(library_ctrl.file_saved)
            queue_ctrl.filesRemoved.connect(library_ctrl.reload)
            queue_ctrl.signInNeeded.connect(lambda site: app_ctrl.notice.emit(
                f"A download needs you to sign in to {context.site(site).label}; open Sign-ins."))
            # A stale browser-window sign-in is re-read quietly first; it often still works.
            queue_ctrl.signInNeeded.connect(signins_ctrl.autoRefresh)
            signins_ctrl.signedIn.connect(queue_ctrl.retrySignIn)
            signins_ctrl.signedIn.connect(analyze_ctrl.signedIn)
            library_ctrl.redownloadRequested.connect(
                lambda url: queue_ctrl.download_again(url, str(load_settings().get("downloads", {}).get("preset", ""))))
            tools_ctrl.toolsReady.connect(queue_ctrl.refresh_settings)
            for source in (queue_ctrl, analyze_ctrl, library_ctrl, subs_ctrl, signins_ctrl, tools_ctrl, player_ctrl):
                source.notice.connect(app_ctrl.notice)

            engine = QQmlApplicationEngine()
            ctx = engine.rootContext()
            controllers = {
                "appController": app_ctrl, "prefsController": prefs_ctrl, "queueController": queue_ctrl,
                "analyzeController": analyze_ctrl, "libraryController": library_ctrl,
                "subscriptionsController": subs_ctrl, "signInsController": signins_ctrl,
                "toolsController": tools_ctrl, "updateController": update_ctrl, "thumbnails": thumbnails,
                "playerController": player_ctrl,
            }
            for name, controller in controllers.items():
                ctx.setContextProperty(name, controller)

            qml_dir = resource_path("gfgmd/qml")
            engine.addImportPath(qml_dir)
            engine.load(os.path.join(qml_dir, "main.qml"))
            if not engine.rootObjects():
                self._on_failed("The user interface failed to load.")
                return

            self._root = cast(QWindow, engine.rootObjects()[0])
            queue_ctrl.attach_window(int(self._root.winId()))
            # Kept alive for the app's lifetime; QML's context properties hold only weak references.
            self._engine = engine
            self._controllers = controllers
            self._context = context

            self._instance.activationRequested.connect(self._show_window)
            self._instance.filesReceived.connect(self._on_launch_request)
            self._instance.noticeReceived.connect(app_ctrl.notice)
            self._build_tray(notifier)
            self._apply_preferences()
            QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)

            settings = load_settings()
            start_hidden = self._tray is not None and (
                self._background or bool(settings.get("tray", {}).get("start_minimized")))
            if not start_hidden:
                self._show_window()
            app_ctrl.show_notices()
            if self._links:
                queue_ctrl.addLinks("\n".join(self._links), str(settings.get("downloads", {}).get("preset", "")))
            self._instance.attach()
            update_ctrl.start()
            tools_ctrl.refresh()
            self._splash.close()
        except Exception as error:  # the start-up boundary: anything here would leave no window
            write_log(f"Startup error: {error}", "critical", force=True)
            self._on_failed(f"The window couldn't be built: {error}")

    def _build_tray(self, notifier: Any) -> None:
        """Create the tray icon and its menu, when a tray is available."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            notifier.attach(None)
            return
        queue = self._controllers["queueController"]
        subs = self._controllers["subscriptionsController"]
        player = self._controllers["playerController"]
        tray = QSystemTrayIcon(_load_icon(), self._app)
        tray.setToolTip(f"{AppInfo.APP_NAME} {AppInfo.APP_VERSION}")
        menu = QMenu()
        entries = [
            (f"Show {AppInfo.APP_NAME}", self._show_window),
            ("Download the copied link", self._download_clipboard),
            ("Play or pause the music", player.togglePlayRequested.emit),
            None,
            ("Pause all downloads", queue.pauseAll),
            ("Resume all downloads", queue.resumeAll),
            ("Check subscriptions now", subs.checkAll),
            None,
            ("Quit", self._app.quit),
        ]
        for entry in entries:
            if entry is None:
                menu.addSeparator()
                continue
            action = QAction(entry[0], menu)
            action.triggered.connect(entry[1])
            menu.addAction(action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray
        self._tray_menu = menu
        notifier.attach(tray)
        queue.changed.connect(self._update_tray_tip)

    def _update_tray_tip(self) -> None:
        if self._tray is None:
            return
        queue = self._controllers["queueController"]
        tip = f"{AppInfo.APP_NAME}"
        if queue.runningCount:
            tip += f"\n{queue.runningCount} downloading" + (f", {queue.speedText}" if queue.speedText else "")
        self._tray.setToolTip(tip)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_window()

    def _show_window(self) -> None:
        """Bring the main window to the front (from the tray, a notification, or a second launch)."""
        if self._root is None:
            return
        self._root.show()
        if self._root.visibility() == QWindow.Visibility.Minimized:
            self._root.showNormal()
        self._root.raise_()
        self._root.requestActivate()

    def _download_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        queue = self._controllers["queueController"]
        if not text or not queue.addLinks(text, str(load_settings().get("downloads", {}).get("preset", ""))):
            self._controllers["appController"].notice.emit("The clipboard has no link to download.")

    def _on_launch_request(self, mode: str, values: list[str]) -> None:
        """A later launch, the command-line tool, or the companion extension handed something over."""
        if mode == _LINKS_MODE:
            links = _links_in(values)
            if links:
                preset = str(load_settings().get("downloads", {}).get("preset", ""))
                self._controllers["queueController"].addLinks("\n".join(links), preset)
        elif mode == _SIGNIN_MODE and len(values) == 2:
            cookies = cookies_from_extension(values[1])
            self._controllers["signInsController"].receive_cookies(values[0], cookies)

    def _on_clipboard(self) -> None:
        """Offer to download a copied link (Preferences > General > Watch the clipboard)."""
        if not load_settings().get("clipboard", {}).get("watch", False):
            return
        text = QGuiApplication.clipboard().text().strip()
        if not text or text == self._last_clipboard or "\n" in text or len(text) > 2048:
            return
        self._last_clipboard = text
        if likely_media(text):
            self._controllers["appController"].clipboardLink.emit(text)

    def _apply_preferences(self) -> None:
        """Apply the side effects of preferences that changed since the last call."""
        settings = load_settings()
        current = {
            "start_with_windows": bool(settings.get("startup", {}).get("start_with_windows", False)),
            "tools": dict(settings.get("tools", {})),
            "schedule": (str(settings.get("schedule", {}).get("queue_start", "")),
                         repr(settings.get("network", {}))),
        }
        previous = self._applied
        app_ctrl = self._controllers.get("appController")
        if current["start_with_windows"] != previous.get("start_with_windows") and autostart.available():
            if current["start_with_windows"] != autostart.is_enabled():
                ok, message = autostart.enable() if current["start_with_windows"] else autostart.disable()
                if not ok and app_ctrl is not None:
                    app_ctrl.notice.emit(message)
        if previous and current["tools"] != previous.get("tools"):
            self._controllers["toolsController"].settings_changed()
        if previous and current["schedule"] != previous.get("schedule"):
            self._controllers["queueController"].refresh_settings()
        self._applied = current

    def _on_failed(self, message: str) -> None:
        """Log the failure, show it, and quit instead of hanging silently."""
        write_log(f"Startup failed: {message}", "critical", force=True)
        self._splash.close()
        QMessageBox.critical(None, AppInfo.APP_NAME, f"{AppInfo.APP_NAME} couldn't start:\n\n{message}")
        self._app.exit(-1)

    def shutdown(self) -> None:
        """Stop downloads (they resume next time), background work, and the tray before exit."""
        for name in ("queueController", "analyzeController", "subscriptionsController", "signInsController",
                     "toolsController", "prefsController", "updateController", "thumbnails", "playerController"):
            controller = self._controllers.get(name)
            if controller is not None:
                controller.shutdown()
        if self._tray is not None:
            self._tray.hide()
        self._instance.close()
        self._engine = None
        if self._context is not None:
            self._context.close()

    def install_update(self) -> None:
        """Hand a downloaded update to its installer; the last step before the process exits."""
        update_ctrl = self._controllers.get("updateController")
        if update_ctrl is not None:
            update_ctrl.install_on_exit()


def _update_config():
    """The updater's settings for this copy: its feed and keys, state file, preferences, and log.

    The update modules were imported by the boot thread. A local staging build (scripts\\bundle.ps1
    -UpdateFeed) adds gfgmd\\config\\update_staging.py, which points the feed at a test server
    with a test key; release builds never contain it.
    """
    from gfgmd.config.defaults import UpdateDefaults, UpdateInfo
    from gfgmd.controllers.update_ctrl import UpdaterConfig
    from gfgmd.services.update_feed import UpdateSource
    from gfgmd.services.update_install import STATE_FILE
    from gfgmd.utils.paths import updates_dir
    from gfgmd.utils.settings import get_settings_file
    from gfgmd.utils.single_instance import release_app_mutexes

    try:
        from gfgmd.config import update_staging  # type: ignore[attr-defined]
    except ImportError:
        update_staging = None

    def read_prefs() -> tuple[bool, bool]:
        updates = load_settings().get("updates", {})
        return (bool(updates.get("auto_check", UpdateDefaults.AUTO_CHECK)),
                bool(updates.get("auto_install", UpdateDefaults.AUTO_INSTALL)))

    source = UpdateSource(
        app=AppInfo.APP_NAME,
        version=AppInfo.APP_VERSION,
        base_url=getattr(update_staging, "BASE_URL", UpdateInfo.REPO_URL),
        public_keys=tuple(getattr(update_staging, "PUBLIC_KEYS", UpdateInfo.PUBLIC_KEYS)),
        allow_local_http=update_staging is not None,
    )
    return UpdaterConfig(
        source=source,
        state_path=os.path.join(os.path.dirname(get_settings_file()), STATE_FILE),
        downloads_dir=updates_dir(),
        read_prefs=read_prefs,
        log=lambda message, error: write_log(message, "critical" if error else "general"),
        release_locks=release_app_mutexes,
        exit_word="quit",  # closing the window keeps the app running in the tray
    )


def _load_icon() -> QIcon:
    """The app icon built from the bundled target-size PNGs."""
    icon = QIcon()
    for size, relative in WINDOW_ICONS.items():
        path = resource_path(relative)
        if os.path.isfile(path):
            icon.addFile(path, QSize(size, size))
    return icon


def main() -> None:
    """Start the app: hand a later launch (and its links) to the open window, or boot a new one."""
    QQuickStyle.setStyle("Material")
    # The players use Qt's FFmpeg backend (hardware decoding where the GPU allows); the bundle ships
    # only that one, so it is named here rather than left to Qt's choice.
    os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

    if _SELF_TEST_FLAG in sys.argv:
        index = sys.argv.index(_SELF_TEST_FLAG)
        sys.exit(run_self_test(sys.argv[index + 1] if index + 1 < len(sys.argv) else None))

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(AppInfo.APP_NAME)
    app.setApplicationVersion(AppInfo.APP_VERSION)

    links = _links_in(sys.argv[1:])
    background = autostart.BACKGROUND_FLAG in sys.argv
    instance = SingleInstance()
    request = LaunchRequest(_LINKS_MODE, tuple(links)) if links else LaunchRequest()
    if instance.try_forward(request):
        sys.exit(0)
    hold_app_mutexes()

    # The tray keeps the app running with no window open, and the QML window closes to the tray,
    # so Qt must not quit when the last window closes.
    app.setQuitOnLastWindowClosed(False)

    startup = _Startup(app, instance, background, links)
    code = app.exec()
    startup.shutdown()
    startup.install_update()
    sys.exit(code)


if __name__ == "__main__":
    main()
