# signins_ctrl.py - website sign-ins: browser window, companion extension, Firefox, or a cookies file
#
# Signing in lets yt-dlp download what a site shows only to signed-in accounts (age-restricted,
# members-only, private playlists, Instagram and Facebook posts). Cookies stay encrypted on this PC
# (see core/auth.py); each download gets a short-lived copy of only its own site's cookies.
#
# The everyday way in is a browser window: the user's default browser (or Edge) opens the site's
# sign-in page on a profile of its own; the user signs in and clicks Done here, and the app closes
# that window and reads the sign-in. A YouTube sign-in is then checked by opening Watch later.

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gfgmd.core.auth import Cookie, drop_expired, for_site, import_cookies, session_expiry, signed_in
from gfgmd.core.command import Auth, account_check_command
from gfgmd.core.errors import classify
from gfgmd.core.runner import Runner
from gfgmd.core.runner import run_to_completion
from gfgmd.core.secret_store import SecretError
from gfgmd.core.sites import SITES, Site, resolve_site
from gfgmd.core.sources import check_url
from gfgmd.models.list_model import DictListModel
from gfgmd.services.browser_signin import (
    Browser,
    SignInError,
    close_window,
    default_browser_key,
    find_browsers,
    open_window,
    read_cookies,
    window_open,
)
from gfgmd.services.context import AppContext
from gfgmd.services.recycle import to_recycle_bin
from gfgmd.services.tasks import TaskRunner
from gfgmd.utils.logging import write_log

ROLES = ("siteKey", "label", "status", "statusText", "method", "methodText", "detail", "busy", "canRefresh", "known",
         "windowOpen", "library")
_METHOD_TEXT = {"browser": "Browser window", "extension": "Browser extension", "firefox": "Firefox",
                "file": "Imported file"}
# Failures that mean a sign-in doesn't work (as opposed to a network hiccup during the check).
_SIGNED_OUT = {"auth_required", "cookies_stale", "private_signin", "bot_check", "removed"}
# A stale browser-window sign-in is re-read by itself at most this often per site.
AUTO_REFRESH_SECONDS = 600
# Far larger than any browser's cookies.txt export, so a bigger file is something else.
_MAX_IMPORT_BYTES = 8 * 1024 * 1024


class SignInsController(QObject):
    """The Sign-ins page."""

    changed = Signal()
    notice = Signal(str)
    # A site now has a working sign-in (the queue retries what waited for it).
    signedIn = Signal(str)
    # A cookies file was imported; QML offers to move the original to the Recycle Bin.
    offerDeleteOriginal = Signal(str)

    def __init__(self, context: AppContext, parent: QObject | None = None, runner: Runner = run_to_completion) -> None:
        super().__init__(parent)
        self._context = context
        # Runs the sign-in check's yt-dlp; tests pass a fake so they never contact a site.
        self._program_runner = runner
        self._model = DictListModel(ROLES, "siteKey", self)
        self._runner = TaskRunner(1, self)
        self._browsers = find_browsers()
        self._busy: set[str] = set()
        self._windows: dict[str, tuple[subprocess.Popen[bytes], Browser]] = {}
        self._extra: dict[str, Site] = {}
        # site key -> (works: True, False, or None when the check couldn't tell, when it ran)
        self._checks: dict[str, tuple[bool | None, float]] = {}
        self._auto_refreshed: dict[str, float] = {}
        self._watch = QTimer(self)
        self._watch.setInterval(1000)
        self._watch.timeout.connect(self._watch_windows)
        self._sync()

    @Property(QObject, constant=True)
    def model(self) -> DictListModel:
        return self._model

    @Property(list, constant=True)
    def browsers(self) -> list[dict[str, str]]:
        """Installed browsers that can open a sign-in window, the Windows default first."""
        default = default_browser_key()
        return [{"label": browser.label + (" (your default)" if browser.key == default else ""), "code": browser.key}
                for browser in self._browsers]

    def _site(self, key: str) -> Site:
        return self._extra.get(key) or self._context.site(key)

    # ── Methods ───────────────────────────────────────────────────────────

    @Slot(str, result=str)
    def addSite(self, link_or_domain: str) -> str:
        """Add another site by link or domain; returns its key ("" when it isn't a usable address)."""
        text = link_or_domain.strip()
        if "://" not in text:
            text = "https://" + text
        try:
            check_url(text)
        except ValueError:
            self.notice.emit("Type a site address, such as example.com, or paste a link from the site.")
            return ""
        host = text.split("://", 1)[1].split("/", 1)[0].split(":")[0]
        site = resolve_site(host)
        if site.key not in {s.key for s in SITES}:
            self._extra[site.key] = site
        self._sync()
        return site.key

    @Slot(str, str)
    def importFile(self, site_key: str, file_path: str) -> None:
        """Import the site's cookies from a Netscape cookies.txt exported from a browser."""
        site = self._site(site_key)
        path = Path(file_path)
        try:
            if path.stat().st_size > _MAX_IMPORT_BYTES:
                self.notice.emit("That file is too large to be a sign-in file saved from a browser.")
                return
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as error:
            write_log(f"Reading the sign-in file {path} failed: {error}", "critical")
            self.notice.emit("That file couldn't be opened. Check that it still exists, then try again.")
            return
        try:
            cookies = import_cookies(text, site)
        except ValueError as error:  # its message says what the file lacks, in the user's words
            self.notice.emit(str(error))
            return
        self._save(site, cookies, "file")
        self.offerDeleteOriginal.emit(str(path))

    @Slot(str)
    def deleteOriginal(self, path: str) -> None:
        """Move an imported cookies file to the Recycle Bin (it gives access to the account)."""
        if to_recycle_bin([path]):
            self.notice.emit("The sign-in file is in the Recycle Bin.")

    @Slot(str, str)
    def useFirefox(self, site_key: str, profile: str) -> None:
        """Read the site's cookies from Firefox on each download (Firefox must have signed in)."""
        site = self._site(site_key)
        browser = "firefox" + (f":{profile.strip()}" if profile.strip() else "")
        self._context.store.save_account(site.key, site.label, "firefox", list(site.cookie_domains), browser)
        self.notice.emit(f"{site.label} downloads will use your Firefox sign-in.")
        self.signedIn.emit(site.key)
        self._sync()

    @Slot(str, str)
    def openBrowserWindow(self, site_key: str, browser_key: str) -> None:
        """Open the site's sign-in page in a browser window of its own ("" picks the default browser).

        Clicking Done (or closing the window) finishes the sign-in.
        """
        site = self._site(site_key)
        browser = next((b for b in self._browsers if b.key == browser_key or not browser_key), None)
        if browser is None:
            self.notice.emit("No supported browser was found (Edge, Chrome, Brave, Vivaldi, or Firefox).")
            return
        if site.key in self._windows:
            self.notice.emit(f"The {site.label} sign-in window is already open.")
            return
        try:
            process = open_window(browser, self._profile(site.key, browser.key), site.login_url)
        except SignInError as error:
            write_log(f"Opening the {site.label} sign-in window failed: {error}", "critical")
            self.notice.emit(f"{browser.label} couldn't be opened. Try another browser under Other ways.")
            return
        self._windows[site.key] = (process, browser)
        self._watch.start()
        self.notice.emit(f"Sign in to {site.label} in the {browser.label} window, then click Done here.")
        self._sync()

    @Slot(str)
    def finishBrowserWindow(self, site_key: str) -> None:
        """Done: close the sign-in window cleanly (so it saves its cookies) and read the sign-in."""
        window = self._windows.pop(site_key, None)
        if window is None:
            return
        process, browser = window
        self._read_browser(site_key, browser, process)

    @Slot(str)
    def cancelBrowserWindow(self, site_key: str) -> None:
        """Close the sign-in window without reading it."""
        window = self._windows.pop(site_key, None)
        if window is None:
            return
        process, browser = window
        self._runner.start(close_window, process, browser, self._profile(site_key, browser.key),
                           on_done=lambda _result: self._sync(), on_error=lambda _message: self._sync())
        self._sync()

    def _profile(self, site_key: str, browser_key: str) -> Path:
        return self._context.signin_profiles / f"{site_key}-{browser_key}"

    def _watch_windows(self) -> None:
        """A sign-in window the user closed themselves finishes the sign-in as Done would."""
        for site_key, (process, browser) in list(self._windows.items()):
            if not window_open(process, browser, self._profile(site_key, browser.key)):
                del self._windows[site_key]
                self._read_browser(site_key, browser)
        if not self._windows:
            self._watch.stop()

    def _read_browser(self, site_key: str, browser: Browser,
                      process: subprocess.Popen[bytes] | None = None) -> None:
        site = self._site(site_key)
        profile = self._profile(site_key, browser.key)
        self._busy.add(site_key)
        self._sync()

        def read() -> list[Cookie]:
            if process is not None:
                close_window(process, browser, profile)
            return read_cookies(browser, profile)

        # The reason is in the log already (the task runner writes it).
        unreadable = (f"The app couldn't read your sign-in from {browser.label}. Close any windows opened for "
                      "this sign-in, then try again.")
        self._runner.start(read, on_done=lambda cookies, s=site, b=browser: self._browser_done(s, b, cookies),
                           on_error=lambda _message, k=site_key: self._fail(k, unreadable))

    def _browser_done(self, site: Site, browser: Browser, cookies: list[Cookie]) -> None:
        mine = drop_expired(for_site(cookies, site))
        if not signed_in(mine, site):
            self._fail(site.key, f"The app found no {site.label} sign-in. Click Sign in, sign in to the site, "
                                 "then click Done.")
            return
        self._save(site, mine, "browser", browser.key)

    @Slot(str)
    def refresh(self, site_key: str) -> None:
        """Read a browser-window sign-in again (sites renew their cookies)."""
        account = self._context.store.account_for_site(site_key)
        browser = next((b for b in self._browsers if account and b.key == account["browser"]), None)
        if account is None or account["method"] != "browser" or browser is None:
            self.notice.emit("To renew this sign-in, sign in again.")
            return
        self._read_browser(site_key, browser)

    @Slot(str)
    def autoRefresh(self, site_key: str) -> None:
        """A download found the saved sign-in stale: re-read a browser-window sign-in quietly.

        At most once every AUTO_REFRESH_SECONDS per site, so a sign-in the site has ended for good
        doesn't keep the queue retrying; it then waits for the user to sign in again.
        """
        account = self._context.store.account_for_site(site_key)
        now = time.monotonic()
        if (account is None or account["method"] != "browser" or site_key in self._busy
                or now - self._auto_refreshed.get(site_key, -AUTO_REFRESH_SECONDS) < AUTO_REFRESH_SECONDS):
            return
        browser = next((b for b in self._browsers if b.key == account["browser"]), None)
        if browser is not None:
            self._auto_refreshed[site_key] = now
            self._read_browser(site_key, browser)

    def receive_cookies(self, site_key: str, cookies: list[Cookie]) -> None:
        """Cookies sent by the companion browser extension for one site."""
        site = self._site(site_key)
        mine = drop_expired(for_site(cookies, site))
        if not signed_in(mine, site):
            self.notice.emit(f"The browser extension sent no {site.label} sign-in. Sign in to {site.label} "
                             "in your browser, then try again.")
            return
        self._save(site, mine, "extension")

    @Slot(str)
    def signOut(self, site_key: str) -> None:
        """Delete the saved sign-in (and its browser profile) from this PC."""
        account = self._context.store.account_for_site(site_key)
        if account is not None:
            self._context.vault.delete(account["id"])
            self._context.store.delete_account(account["id"])
        for browser in self._browsers:
            shutil.rmtree(self._profile(site_key, browser.key), ignore_errors=True)
        self.notice.emit(f"Signed out of {self._site(site_key).label} on this PC. To sign out everywhere, "
                         "also sign out on the site.")
        self._sync()

    # ── Shared ────────────────────────────────────────────────────────────

    def _save(self, site: Site, cookies: list[Cookie], method: str, browser: str = "") -> None:
        try:
            account_id = self._context.store.save_account(site.key, site.label, method, list(site.cookie_domains),
                                                          browser, session_expiry(cookies, site))
            self._context.vault.save(account_id, cookies)
        except (OSError, SecretError) as error:
            write_log(f"Saving the {site.label} sign-in failed: {error}", "critical")
            self._fail(site.key, "The sign-in couldn't be saved on this PC. Try again.")
            return
        if site.check_url:
            self._check(site, account_id)
            return
        self._busy.discard(site.key)
        self.notice.emit(f"Signed in to {site.label}.")
        self.signedIn.emit(site.key)
        self._sync()

    def _check(self, site: Site, account_id: int) -> None:
        """Prove a new sign-in works by opening a list only the account can see (YouTube's Watch later)."""
        self._busy.add(site.key)
        self._sync()
        self._runner.start(self._run_check, site, account_id,
                           on_done=lambda works, s=site: self._checked(s, works),
                           on_error=lambda _message, s=site: self._checked(s, None))

    def _run_check(self, site: Site, account_id: int) -> bool | None:
        """On the pool: True when the list opened, False when the site refused the sign-in, None when unsure."""
        context = self._context
        tools = context.tools()
        checkout = context.vault.checkout(account_id, site, context.run_root / f"check-{int(time.time() * 1000)}")
        errors: list[str] = []

        def collect(_stream: str, line: str) -> None:
            if line.startswith("ERROR:"):
                errors.append(line[6:].strip())

        try:
            command = account_check_command(site.check_url, tools, context.cache_dir,
                                            Auth(cookies_file=str(checkout.path)))
            code, _stopped = self._program_runner(command, collect, None)
        finally:
            context.vault.checkin(account_id, checkout)
        if code == 0:
            return True
        failure = classify(errors[-1] if errors else "", signed_in=False)
        return False if failure.category.key in _SIGNED_OUT else None

    def _checked(self, site: Site, works: bool | None) -> None:
        self._checks[site.key] = (works, time.time())
        self._busy.discard(site.key)
        account = self._context.store.account_for_site(site.key)
        if works is False:
            if account is not None:
                self._context.store.update_account(account["id"], status="expired")
            self.notice.emit(f"{site.label} didn't accept that sign-in. Sign in again, then click Done.")
        else:
            if account is not None:
                self._context.store.update_account(account["id"], status="ok")
            self.notice.emit(f"Signed in to {site.label}." if works else
                             f"Signed in to {site.label}. The app couldn't test it right now; your next "
                             "download will show whether it works.")
            self.signedIn.emit(site.key)
        self._sync()

    def _fail(self, site_key: str, message: str) -> None:
        self._busy.discard(site_key)
        self.notice.emit(message)
        self._sync()

    def _sync(self) -> None:
        accounts = {account["site"]: account for account in self._context.store.accounts()}
        sites = [site for site in SITES if site.signs_in] + list(self._extra.values())
        sites += [self._context.site(key) for key in accounts if key not in {s.key for s in sites}]
        rows = []
        for site in sites:
            account = accounts.get(site.key)
            rows.append(self._row(site, account))
        self._model.sync(rows)
        self.changed.emit()

    def _row(self, site: Site, account: dict[str, Any] | None) -> dict[str, Any]:
        status, text, detail = "none", "Not signed in", ""
        if account is not None:
            ended = bool(account["expires"]) and account["expires"] < datetime.now().timestamp()
            expired = account["status"] != "ok" or ended
            stored = account["method"] == "firefox" or self._context.vault.exists(account["id"])
            status = "expired" if expired or not stored else "ok"
            text = "Sign in again" if status == "expired" else "Signed in"
            parts = [f"Saved {datetime.fromtimestamp(account['refreshed']).strftime('%d %b %Y')}"]
            if account["expires"]:
                parts.append(f"expires {datetime.fromtimestamp(account['expires']).strftime('%d %b %Y')}")
            check = self._checks.get(site.key)
            if check is not None and check[0] is not None:
                result = "working" if check[0] else "not accepted by the site"
                parts.append(f"{result} (checked at {datetime.fromtimestamp(check[1]).strftime('%H:%M')})")
            detail = ", ".join(parts)
        if site.key in self._windows:
            text = "Sign in in the browser window, then click Done"
        elif site.key in self._busy:
            text = "Checking the sign-in..." if site.check_url and account else "Reading the sign-in..."
        return {
            "siteKey": site.key, "label": site.label, "status": status, "statusText": text,
            "method": account["method"] if account else "",
            "methodText": _METHOD_TEXT.get(account["method"], "") if account else "", "detail": detail,
            "busy": site.key in self._busy, "canRefresh": bool(account and account["method"] == "browser"),
            "known": site.key in {s.key for s in SITES}, "windowOpen": site.key in self._windows,
            "library": [{"label": label, "url": url} for label, url in site.library] if status == "ok" else [],
        }

    def shutdown(self) -> None:
        self._watch.stop()
        for process, browser in self._windows.values():
            if process.poll() is None:
                process.kill()  # the app is closing; the user can sign in again later
        self._windows.clear()
        self._runner.shutdown(3000)
