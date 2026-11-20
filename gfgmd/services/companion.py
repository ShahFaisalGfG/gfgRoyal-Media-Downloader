# companion.py - the native-messaging host the companion browser extension talks to (stdlib only)
#
# Chromium starts gfgRoyal-Media-Downloader-host.exe when the extension sends a message, passing
# the extension's origin as the first argument. Each message (4-byte length + JSON, Chrome's native
# messaging format) is checked (sender, type, size, fields) and handed to the running app over its
# single-instance pipe; when the app isn't running, the host starts it in the tray and waits for it.
#
# Messages: {"type": "ping"}, {"type": "download", "urls": [...]}, and
# {"type": "signin", "site": key, "cookies": [chrome.cookies.Cookie, ...]}.

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from typing import Any, BinaryIO

from gfgmd.config.defaults import AppInfo
from gfgmd.core.auth import Cookie
from gfgmd.core.sites import SITES
from gfgmd.core.sources import check_url
from gfgmd.utils.launch import LaunchRequest, send

HOST_NAME = "com.gfgroyal.mediadownloader"
# Extensions allowed to use the host: the ID fixed by the manifest key in companion/wxt.config.ts.
# A store listing with its own ID is added here (and to the installers' MyExtId) when it is published.
ALLOWED_ORIGINS = (
    "chrome-extension://gipopofnfbdhmmkpeaffnjfkkdbnjepp/",
)
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_URLS = 200
MAX_COOKIES = 3000
_START_WAIT_S = 15
# What the extension's popup shows. A message the host can't use means the extension and the app
# come from different versions; the host has no log of its own (its standard output is the browser's).
MISMATCH = "The extension and the app don't match. Update both, then try again."
NO_LINK = "There's no link here to download."
TOO_MANY_LINKS = f"Send up to {MAX_URLS} links at a time."
BAD_LINK = "The app can't download from this link. Check that it opens a video, song, or playlist."


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    """One message from the browser, or None at end of input; raises ValueError for a bad message."""
    header = stream.read(4)
    if len(header) < 4:
        return None
    length = struct.unpack("<I", header)[0]
    if length > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    body = stream.read(length)
    if len(body) < length:
        return None
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("message is not an object")
    return message


def write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    """Send one reply to the browser."""
    body = json.dumps(message).encode("utf-8")
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def cookies_from_extension(text: str) -> list[Cookie]:
    """chrome.cookies.Cookie objects (as JSON text) turned into cookie-jar entries; bad ones are skipped."""
    try:
        raw = json.loads(text)
    except ValueError:
        return []
    cookies: list[Cookie] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name, value, domain = item.get("name"), item.get("value"), item.get("domain")
        if not (isinstance(name, str) and isinstance(value, str) and isinstance(domain, str) and name and domain):
            continue
        if len(name) > 256 or len(value) > 8192 or len(domain) > 253:
            continue
        expires = item.get("expirationDate")
        lasting = isinstance(expires, (int, float)) and not item.get("session")
        host_only = bool(item.get("hostOnly"))
        cookies.append(Cookie(
            domain=domain if host_only or domain.startswith(".") else "." + domain,
            path=str(item.get("path") or "/")[:1024],
            name=name, value=value, secure=bool(item.get("secure")),
            expires=int(expires) if lasting and isinstance(expires, (int, float)) else 0,
            http_only=bool(item.get("httpOnly")),
            include_subdomains=not host_only,
        ))
    return cookies


def request_for(message: dict[str, Any]) -> LaunchRequest:
    """The launch request for a valid message; raises ValueError whose message is the reply the popup shows."""
    kind = message.get("type")
    if kind == "download":
        urls = message.get("urls")
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            raise ValueError(MISMATCH)
        if not urls:
            raise ValueError(NO_LINK)
        if len(urls) > MAX_URLS:
            raise ValueError(TOO_MANY_LINKS)
        try:
            checked = tuple(check_url(url) for url in urls)
        except ValueError as error:
            raise ValueError(BAD_LINK) from error
        return LaunchRequest("links", checked)
    if kind == "signin":
        site, cookies = message.get("site"), message.get("cookies")
        known = {site.key for site in SITES}
        if not isinstance(site, str) or not (site in known or _hostname(site)):
            raise ValueError(MISMATCH)
        if not isinstance(cookies, list) or len(cookies) > MAX_COOKIES:
            raise ValueError(MISMATCH)
        return LaunchRequest("signin", (site, json.dumps(cookies)))
    raise ValueError(MISMATCH)


def _hostname(text: str) -> bool:
    return 0 < len(text) <= 253 and all(part.isalnum() or "-" in part for part in text.split(".")) and "." in text


def _app_exe() -> str:
    """The app beside this host (both ship in the same folder)."""
    return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), f"{AppInfo.FILE_NAME}.exe")


def deliver(request: LaunchRequest) -> bool:
    """Hand the request to the app, starting it in the tray first when it isn't running."""
    if send(request):
        return True
    exe = _app_exe()
    if not os.path.isfile(exe):
        return False
    try:
        subprocess.Popen([exe, "--background"], close_fds=True)  # noqa: S603 - our own exe, fixed arguments
    except OSError:
        return False
    deadline = time.monotonic() + _START_WAIT_S
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if send(request):
            return True
    return False


def run(argv: list[str], stdin: BinaryIO, stdout: BinaryIO) -> int:
    """Serve one browser connection: check the caller, then answer each message."""
    origin = argv[1] if len(argv) > 1 else ""
    if origin not in ALLOWED_ORIGINS:
        write_message(stdout, {"ok": False, "message": "This extension isn't allowed to use the app."})
        return 1
    while True:
        try:
            message = read_message(stdin)
        except (ValueError, UnicodeDecodeError):
            write_message(stdout, {"ok": False, "message": MISMATCH})
            return 1
        if message is None:
            return 0
        if message.get("type") == "ping":
            write_message(stdout, {"ok": True, "app": AppInfo.APP_NAME, "version": AppInfo.APP_VERSION})
            continue
        try:
            request = request_for(message)
        except ValueError as error:
            write_message(stdout, {"ok": False, "message": str(error)})
            continue
        if deliver(request):
            write_message(stdout, {"ok": True})
        else:
            write_message(stdout, {"ok": False, "message": f"{AppInfo.APP_NAME} couldn't be reached. Open it and try again."})
