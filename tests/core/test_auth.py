"""Sign-in jars: Netscape round trip, domain filtering, merging, encryption, and wiping."""

import sys
import time
from pathlib import Path

import pytest

from gfgmd.core.auth import Cookie, SignInVault, format_netscape, import_cookies, merge, parse_netscape, session_expiry
from gfgmd.core.secret_store import SecretError, read_secret, write_secret
from gfgmd.core.sites import site_by_key

YOUTUBE = site_by_key("youtube")
FUTURE = int(time.time()) + 86400 * 30


def jar() -> list[Cookie]:
    return [
        Cookie(".youtube.com", "/", "SAPISID", "s1", expires=FUTURE),
        Cookie(".youtube.com", "/", "PREF", "f6=1", secure=False, expires=FUTURE),
        Cookie("accounts.google.com", "/", "LSID", "l1", http_only=True, include_subdomains=False),
        Cookie(".facebook.com", "/", "c_user", "123", expires=FUTURE),
    ]


def test_netscape_round_trip() -> None:
    """Write and read every field, including HttpOnly and session cookies."""
    assert YOUTUBE is not None
    text = format_netscape(jar())
    assert text.startswith("# Netscape HTTP Cookie File\n")
    assert "#HttpOnly_accounts.google.com\tFALSE\t/\tTRUE\t0\tLSID\tl1" in text
    assert parse_netscape(text) == jar()


def test_parse_skips_malformed_lines() -> None:
    text = "# comment\n\nbad line\n.x.com\tTRUE\t/\tTRUE\tnot-a-number\tn\tv\n.x.com\tTRUE\t/\tFALSE\t5\tok\t1\n"
    assert [cookie.name for cookie in parse_netscape(text)] == ["ok"]


def test_import_keeps_only_the_site_and_requires_a_session() -> None:
    """Keep YouTube and Google cookies, drop others and expired ones, and require a sign-in cookie."""
    assert YOUTUBE is not None
    expired = Cookie(".youtube.com", "/", "OLD", "x", expires=int(time.time()) - 10)
    cookies = import_cookies(format_netscape([*jar(), expired]), YOUTUBE)
    assert {cookie.name for cookie in cookies} == {"SAPISID", "PREF", "LSID"}
    with pytest.raises(ValueError, match="signed-in"):
        import_cookies(format_netscape([jar()[1]]), YOUTUBE)
    with pytest.raises(ValueError, match="no YouTube cookies"):
        import_cookies(format_netscape([jar()[3]]), YOUTUBE)
    assert session_expiry(cookies, YOUTUBE) == FUTURE


def test_merge_keeps_both_sides_changes() -> None:
    """Apply what a run changed on top of what changed in the jar meanwhile."""
    base = jar()[:3]
    theirs = [Cookie(".youtube.com", "/", "SAPISID", "rotated", expires=FUTURE), jar()[1],
              Cookie(".youtube.com", "/", "NEW", "n")]  # changed, kept, added; LSID deleted
    ours = [*base, Cookie(".youtube.com", "/", "MEANWHILE", "m")]
    merged = {cookie.name: cookie.value for cookie in merge(base, theirs, ours)}
    assert merged == {"SAPISID": "rotated", "PREF": "f6=1", "NEW": "n", "MEANWHILE": "m"}


def test_secret_round_trip(tmp_path: Path) -> None:
    """Read back what was written."""
    path = tmp_path / "1.bin"
    write_secret(path, b"secret cookies", b"one")
    assert read_secret(path, b"one") == b"secret cookies"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_dpapi_encrypts_and_binds_to_the_key(tmp_path: Path) -> None:
    """The file holds no plain text, and a different key can't decrypt it."""
    path = tmp_path / "1.bin"
    write_secret(path, b"secret cookies", b"one")
    assert b"secret cookies" not in path.read_bytes()
    with pytest.raises(SecretError):
        read_secret(path, b"two")


def test_checkout_and_checkin_wipe_and_merge(tmp_path: Path) -> None:
    """Hand out only the site's cookies, take back rotations, and leave no plain file behind."""
    assert YOUTUBE is not None
    vault = SignInVault(tmp_path / "signins")
    vault.save(7, jar())
    checkout = vault.checkout(7, YOUTUBE, tmp_path / "run" / "job-1")
    handed = parse_netscape(checkout.path.read_text(encoding="utf-8"))
    assert {cookie.name for cookie in handed} == {"SAPISID", "PREF", "LSID"}
    rotated = [Cookie(".youtube.com", "/", "SAPISID", "rotated", expires=FUTURE), *handed[1:]]
    checkout.path.write_text(format_netscape(rotated), encoding="utf-8")
    vault.checkin(7, checkout)
    assert not checkout.path.exists()
    stored = {cookie.name: cookie.value for cookie in vault.load(7)}
    assert stored["SAPISID"] == "rotated" and stored["c_user"] == "123"


def test_checkin_after_sign_out_does_not_restore(tmp_path: Path) -> None:
    """A run that ends after the user signed out doesn't bring the cookies back."""
    assert YOUTUBE is not None
    vault = SignInVault(tmp_path / "signins")
    vault.save(3, jar())
    checkout = vault.checkout(3, YOUTUBE, tmp_path / "run")
    vault.delete(3)
    vault.checkin(3, checkout)
    assert not vault.exists(3) and not checkout.path.exists()
