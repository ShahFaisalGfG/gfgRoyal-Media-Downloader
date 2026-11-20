# browser_signin.py - sign in to a site in an installed browser's window, then read that window's cookies
#
# Google and other sites refuse sign-ins inside embedded browser frameworks, and browsers protect
# their everyday profile's cookies from other programs. So the app opens one of the user's installed
# browsers (their Windows default when it can) on a dedicated profile kept in the app's data folder,
# with no remote control attached while the user signs in: to the site it is a normal browser.
# Chromium browsers (Edge, Chrome, Brave, Vivaldi) open as a plain app window with no tabs or address
# bar. When the user clicks Done in the app (or closes the window), the app closes the browser
# cleanly so it saves its cookies, then reads them: a Chromium profile is started headless with
# DevTools on a private pipe (no port another program could reach) and asked for its cookies
# (Storage.getCookies); a Firefox profile's cookie database is read directly. Refreshing a sign-in
# repeats only that read, with no window.
#
# Opera isn't offered: its launcher exits at once and starts the browser separately, so the app
# couldn't tell when the sign-in window closes.

from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from gfgmd.core.auth import Cookie
from gfgmd.core.platform import ProcessGroup
from gfgmd.services.cdp import CdpError, CdpPipe

if sys.platform == "win32":
    import winreg

# (key, label, exe, folders under Program Files or LocalAppData, engine, Windows ProgId prefixes)
_BROWSERS = (
    ("edge", "Microsoft Edge", "msedge.exe", (r"Microsoft\Edge\Application",), "chromium", ("MSEdgeHTM",)),
    ("chrome", "Google Chrome", "chrome.exe", (r"Google\Chrome\Application",), "chromium", ("ChromeHTML",)),
    ("brave", "Brave", "brave.exe", (r"BraveSoftware\Brave-Browser\Application",), "chromium", ("BraveHTML",)),
    ("vivaldi", "Vivaldi", "vivaldi.exe", (r"Vivaldi\Application",), "chromium", ("VivaldiHTM",)),
    ("firefox", "Mozilla Firefox", "firefox.exe", (r"Mozilla Firefox",), "firefox", ("FirefoxURL", "FirefoxHTML")),
)
_COMMON_FLAGS = ("--no-first-run", "--no-default-browser-check", "--disable-sync")
# A sign-in page fits comfortably in this window.
_WINDOW_SIZE = "--window-size=520,760"
# A fresh Firefox profile would otherwise open welcome and privacy-notice tabs first.
_FIREFOX_PREFS = """user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.sessionstore.resume_from_crash", false);
"""
_WM_CLOSE = 0x0010


class SignInError(Exception):
    """The browser sign-in couldn't be started or its cookies couldn't be read; the message suits the log."""


@dataclass(frozen=True)
class Browser:
    """An installed browser the app can open a sign-in window in."""

    key: str
    label: str
    exe: str
    engine: str = "chromium"  # or "firefox"


def find_browsers() -> list[Browser]:
    """Installed browsers that support a separate profile: the Windows default first, then Edge first."""
    found: list[Browser] = []
    for key, label, exe, folders, engine, _prog_ids in _BROWSERS:
        path = _app_path(exe) or _known_path(folders, exe)
        if path:
            found.append(Browser(key, label, path, engine))
    default = default_browser_key()
    return sorted(found, key=lambda browser: browser.key != default)


def default_browser_key() -> str:
    """The key of the user's default web browser, or "" when it isn't one the app can open."""
    if sys.platform != "win32":
        return ""
    path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except OSError:
        return ""
    for browser_key, *_rest, prog_ids in _BROWSERS:
        if isinstance(prog_id, str) and prog_id.startswith(prog_ids):
            return browser_key
    return ""


def _app_path(exe: str) -> str:
    if sys.platform != "win32":
        return ""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value, _ = winreg.QueryValueEx(key, "")
            if isinstance(value, str) and os.path.isfile(value.strip('"')):
                return value.strip('"')
        except OSError:
            continue
    return ""


def _known_path(folders: tuple[str, ...], exe: str) -> str:
    bases = [os.environ.get(name, "") for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    for base in filter(None, bases):
        for folder in folders:
            candidate = os.path.join(base, folder, exe)
            if os.path.isfile(candidate):
                return candidate
    return ""


def prepare_profile(browser: Browser, profile: Path) -> None:
    """Create the dedicated profile so the browser opens straight to the sign-in page and quits on close."""
    profile.mkdir(parents=True, exist_ok=True)
    if browser.engine == "firefox":
        user_js = profile / "user.js"
        if not user_js.exists():
            user_js.write_text(_FIREFOX_PREFS, encoding="utf-8")
        return
    local_state = profile / "Local State"
    if not local_state.exists():
        local_state.write_text(json.dumps({"background_mode": {"enabled": False}}), encoding="utf-8")


def open_window(browser: Browser, profile: Path, url: str) -> subprocess.Popen[bytes]:
    """Open the site's sign-in page in the dedicated profile: an app window, or a Firefox window."""
    prepare_profile(browser, profile)
    if browser.engine == "firefox":
        command = [browser.exe, "-profile", str(profile), "-no-remote", "-new-instance", url]
    else:
        command = [browser.exe, f"--user-data-dir={profile}", *_COMMON_FLAGS, _WINDOW_SIZE, f"--app={url}"]
    try:
        return subprocess.Popen(command)
    except OSError as error:
        raise SignInError(f"{browser.label} didn't start: {error}") from error


def window_open(process: subprocess.Popen[bytes], browser: Browser, profile: Path) -> bool:
    """True while the sign-in browser is still running (a Chromium profile holds its lockfile until it quits)."""
    if process.poll() is None:
        return True
    return browser.engine == "chromium" and (profile / "lockfile").exists()


def close_window(process: subprocess.Popen[bytes], browser: Browser, profile: Path, timeout: float = 15.0) -> None:
    """Ask the sign-in browser to close its windows, as clicking X would, so it saves its cookies.

    A browser still running after `timeout` seconds is ended; its newest cookies may then be missing.
    """
    if process.poll() is None:
        _post_close(process.pid)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and window_open(process, browser, profile):
        time.sleep(0.2)
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)


def _post_close(pid: int) -> None:
    """Send WM_CLOSE to the visible top-level windows of process `pid`."""
    if sys.platform != "win32":
        os.kill(pid, signal.SIGTERM)
        return
    user32 = ctypes.windll.user32
    windows: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd: int, _param: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            windows.append(hwnd)
        return True

    user32.EnumWindows(callback_type(collect), None)
    for hwnd in windows:
        user32.PostMessageW(ctypes.c_void_p(hwnd), _WM_CLOSE, 0, 0)


def read_cookies(browser: Browser, profile: Path, timeout: float = 30.0) -> list[Cookie]:
    """The cookies the sign-in profile saved."""
    if not profile.is_dir():
        raise SignInError("Sign in with the browser window first")
    if browser.engine == "firefox":
        return _read_firefox(profile)
    return _read_chromium(browser, profile, timeout)


def _read_chromium(browser: Browser, profile: Path, timeout: float) -> list[Cookie]:
    """Start the profile headless, read every cookie through DevTools on a private pipe, and close
    the browser."""
    group = ProcessGroup()
    pipe: CdpPipe | None = None
    try:
        pipe = CdpPipe(timeout)
        group.launch([browser.exe, f"--user-data-dir={profile}", *_COMMON_FLAGS, "--headless=new",
                      *pipe.browser_args(), "about:blank"], capture=False, inherit=pipe.child_handles())
        pipe.started()
        result = pipe.call("Storage.getCookies")
        pipe.send_only("Browser.close")
        if group.process is not None:
            try:
                group.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
    except (OSError, CdpError, ValueError) as error:
        raise SignInError(f"Couldn't read the sign-in from {browser.label}: {error}") from error
    finally:
        group.kill()
        group.close()
        if pipe is not None:
            pipe.close()
    return [_cookie(raw) for raw in result.get("cookies", []) if isinstance(raw, dict) and raw.get("name")]


def _read_firefox(profile: Path) -> list[Cookie]:
    """Read a closed Firefox profile's cookies.sqlite (Firefox stores cookie values unencrypted).

    The database and its write-ahead log are copied first, so a Firefox that is still open can't
    lock the read, and nothing in the profile is changed.
    """
    source = profile / "cookies.sqlite"
    if not source.is_file():
        raise SignInError("Firefox saved no sign-in; sign in, then click Done")
    with tempfile.TemporaryDirectory(prefix="gfgmd-ff-") as folder:
        copy = Path(folder) / "cookies.sqlite"
        try:
            shutil.copy2(source, copy)
            for suffix in ("-wal", "-shm"):
                extra = profile / f"cookies.sqlite{suffix}"
                if extra.is_file():
                    shutil.copy2(extra, Path(folder) / f"cookies.sqlite{suffix}")
            connection = sqlite3.connect(copy)
            try:
                rows = connection.execute(
                    "SELECT host, path, name, value, isSecure, expiry, isHttpOnly FROM moz_cookies").fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as error:
            raise SignInError(f"Couldn't read the sign-in from Firefox: {error}") from error
    cookies = []
    for host, path, name, value, secure, expiry, http_only in rows:
        if not name:
            continue
        expires = int(expiry or 0)
        if expires > 100_000_000_000:  # newer Firefox versions store milliseconds
            expires //= 1000
        domain = str(host or "")
        cookies.append(Cookie(domain=domain, path=str(path or "/"), name=str(name), value=str(value or ""),
                              secure=bool(secure), expires=max(expires, 0), http_only=bool(http_only),
                              include_subdomains=domain.startswith(".")))
    return cookies


def _cookie(raw: dict) -> Cookie:
    domain = str(raw.get("domain", ""))
    expires = raw.get("expires", -1)
    return Cookie(
        domain=domain,
        path=str(raw.get("path") or "/"),
        name=str(raw["name"]),
        value=str(raw.get("value", "")),
        secure=bool(raw.get("secure")),
        expires=int(expires) if isinstance(expires, (int, float)) and expires > 0 and not raw.get("session") else 0,
        http_only=bool(raw.get("httpOnly")),
        include_subdomains=domain.startswith("."),
    )
