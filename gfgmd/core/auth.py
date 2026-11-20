"""Website sign-ins: cookie jars, kept encrypted per site and handed to yt-dlp one run at a time.

A run gets a plain cookies file holding only the site's own cookies, in a private folder. yt-dlp
may update cookies while it runs (sites rotate session cookies); afterwards the file is read back,
merged into the stored jar (changes made meanwhile by another run or a refresh are kept), the jar
is encrypted again, and the plain file is wiped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from gfgmd.core.locks import FileLock
from gfgmd.core.secret_store import SecretError, read_secret, wipe, write_secret
from gfgmd.core.sites import Site

HEADER = "# Netscape HTTP Cookie File"
_HTTP_ONLY = "#HttpOnly_"


@dataclass(frozen=True)
class Cookie:
    """One cookie in Netscape cookies.txt terms."""

    domain: str
    path: str
    name: str
    value: str
    secure: bool = True
    expires: int = 0  # Unix time; 0 for a session cookie
    http_only: bool = False
    include_subdomains: bool = True

    @property
    def key(self) -> tuple[str, str, str]:
        """What makes two cookies the same cookie."""
        return (self.domain.lower(), self.path, self.name)


def parse_netscape(text: str) -> list[Cookie]:
    """Cookies from a Netscape cookies.txt; malformed lines are skipped."""
    cookies: list[Cookie] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        http_only = line.startswith(_HTTP_ONLY)
        if http_only:
            line = line[len(_HTTP_ONLY):]
        elif not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, subdomains, path, secure, expires, name, value = fields
        try:
            expiry = int(float(expires)) if expires else 0
        except (ValueError, OverflowError):  # not a number, or infinite
            continue
        if not domain or not name:
            continue
        cookies.append(Cookie(domain, path or "/", name, value, secure.upper() == "TRUE", max(expiry, 0),
                              http_only, subdomains.upper() == "TRUE"))
    return cookies


def format_netscape(cookies: Iterable[Cookie]) -> str:
    """A Netscape cookies.txt that yt-dlp reads."""
    lines = [HEADER, "# Written by gfgRoyal Media Downloader for one download; deleted afterwards.", ""]
    for cookie in cookies:
        prefix = _HTTP_ONLY if cookie.http_only else ""
        lines.append("\t".join((
            prefix + cookie.domain,
            "TRUE" if cookie.include_subdomains else "FALSE",
            cookie.path,
            "TRUE" if cookie.secure else "FALSE",
            str(cookie.expires),
            cookie.name,
            cookie.value,
        )))
    return "\n".join(lines) + "\n"


def belongs_to(cookie: Cookie, domains: Iterable[str]) -> bool:
    """True when the cookie's domain is one of `domains` or under one of them."""
    host = cookie.domain.lower().lstrip(".")
    for domain in domains:
        base = domain.lower().lstrip(".")
        if host == base or host.endswith("." + base):
            return True
    return False


def for_site(cookies: Iterable[Cookie], site: Site) -> list[Cookie]:
    """Only the cookies of the site's own domains."""
    return [cookie for cookie in cookies if belongs_to(cookie, site.cookie_domains)]


def drop_expired(cookies: Iterable[Cookie], now: float | None = None) -> list[Cookie]:
    """Cookies that haven't expired (session cookies are kept)."""
    moment = now if now is not None else time.time()
    return [cookie for cookie in cookies if not cookie.expires or cookie.expires > moment]


def signed_in(cookies: Iterable[Cookie], site: Site) -> bool:
    """True when the jar holds one of the cookies that mark a signed-in session for the site."""
    if not site.auth_cookies:
        return any(True for _ in cookies)
    names = {cookie.name for cookie in cookies}
    return any(name in names for name in site.auth_cookies)


def session_expiry(cookies: Iterable[Cookie], site: Site) -> float:
    """When the sign-in ends: the earliest expiry among its session-marking cookies (0 = unknown)."""
    marks = [cookie.expires for cookie in cookies if cookie.name in site.auth_cookies and cookie.expires]
    return float(min(marks)) if marks else 0.0


def merge(base: list[Cookie], theirs: list[Cookie], ours: list[Cookie]) -> list[Cookie]:
    """Three-way merge: apply what a run changed (base -> theirs) on top of the current jar (ours)."""
    base_map = {cookie.key: cookie for cookie in base}
    their_map = {cookie.key: cookie for cookie in theirs}
    result = {cookie.key: cookie for cookie in ours}
    for key, cookie in their_map.items():
        if base_map.get(key) != cookie:
            result[key] = cookie  # added or changed during the run
    for key in base_map.keys() - their_map.keys():
        result.pop(key, None)  # deleted during the run
    return list(result.values())


@dataclass(frozen=True)
class Checkout:
    """A cookies file handed to one run, and what it held."""

    path: Path
    base: tuple[Cookie, ...]


class SignInVault:
    """Encrypted cookie jars, one file per sign-in record id."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _file(self, account_id: int) -> Path:
        return self.folder / f"{account_id}.bin"

    @staticmethod
    def _entropy(account_id: int) -> bytes:
        return f"gfgmd-signin-{account_id}".encode("utf-8")

    def save(self, account_id: int, cookies: Iterable[Cookie]) -> None:
        """Encrypt and store a jar."""
        write_secret(self._file(account_id), format_netscape(cookies).encode("utf-8"), self._entropy(account_id))

    def load(self, account_id: int) -> list[Cookie]:
        """Decrypt a jar; raises SecretError when it can't be read here, FileNotFoundError when absent."""
        data = read_secret(self._file(account_id), self._entropy(account_id))
        return parse_netscape(data.decode("utf-8", errors="replace"))

    def exists(self, account_id: int) -> bool:
        """True when a jar is stored for the record."""
        return self._file(account_id).is_file()

    def delete(self, account_id: int) -> None:
        """Remove a jar."""
        self._file(account_id).unlink(missing_ok=True)

    def checkout(self, account_id: int, site: Site, run_dir: Path) -> Checkout:
        """Write the site's unexpired cookies to a plain file for one run."""
        with FileLock(self._file(account_id), timeout=30):
            cookies = drop_expired(for_site(self.load(account_id), site))
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "cookies.txt"
        path.write_text(format_netscape(cookies), encoding="utf-8", newline="\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return Checkout(path, tuple(cookies))

    def checkin(self, account_id: int, checkout: Checkout) -> None:
        """Merge the run's cookie changes into the stored jar, then wipe the plain file."""
        try:
            try:
                theirs = parse_netscape(checkout.path.read_text(encoding="utf-8", errors="replace"))
            except FileNotFoundError:
                return
            with FileLock(self._file(account_id), timeout=30):
                try:
                    ours = self.load(account_id)
                except (FileNotFoundError, SecretError):
                    return  # signed out (or unreadable) meanwhile: don't bring the cookies back
                self.save(account_id, merge(list(checkout.base), theirs, ours))
        finally:
            wipe(checkout.path)


def import_cookies(text: str, site: Site, now: float | None = None) -> list[Cookie]:
    """The site's unexpired cookies from a cookies.txt.

    Raises ValueError when it holds no sign-in; the message is written for the user.
    """
    cookies = drop_expired(for_site(parse_netscape(text), site), now)
    if not cookies:
        raise ValueError(f"This file has no {site.label} sign-in in it. Save it again from your browser "
                         f"while signed in to {site.label}.")
    if not signed_in(cookies, site):
        raise ValueError(f"This file was saved while signed out of {site.label}. Sign in, save the file again, "
                         "and import the new one.")
    return cookies
