"""The companion's native-messaging host: framing, sender check, validation, and hand-off."""

import io
import json
import struct
from unittest.mock import patch

import pytest

from gfgmd.services import companion
from gfgmd.services.companion import cookies_from_extension, read_message, request_for, run, write_message

ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"


def frame(message: dict) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def replies(data: bytes) -> list[dict]:
    stream = io.BytesIO(data)
    out = []
    while True:
        message = read_message(stream)
        if message is None:
            return out
        out.append(message)


def test_framing_round_trip() -> None:
    stream = io.BytesIO()
    write_message(stream, {"ok": True, "n": "é"})
    stream.seek(0)
    assert read_message(stream) == {"ok": True, "n": "é"}
    assert read_message(io.BytesIO(b"")) is None
    with pytest.raises(ValueError):
        read_message(io.BytesIO(struct.pack("<I", 10 * 1024 * 1024)))


def test_download_requests_are_checked() -> None:
    request = request_for({"type": "download", "urls": ["https://www.youtube.com/watch?v=jNQXAC9IVRw"]})
    assert request.mode == "links" and len(request.paths) == 1
    for bad in ({"type": "download", "urls": []}, {"type": "download", "urls": ["javascript:alert(1)"]},
                {"type": "download", "urls": [5]}, {"type": "exec", "command": "calc"},
                {"type": "download", "urls": ["https://x.com"] * 201}):
        with pytest.raises(ValueError):
            request_for(bad)


def test_signin_requests_are_checked() -> None:
    request = request_for({"type": "signin", "site": "youtube", "cookies": [{"name": "a", "value": "b"}]})
    assert request.mode == "signin" and request.paths[0] == "youtube"
    assert request_for({"type": "signin", "site": "media.example.org", "cookies": []}).paths[0] == "media.example.org"
    for bad in ({"type": "signin", "site": "../../etc", "cookies": []}, {"type": "signin", "site": "youtube"},
                {"type": "signin", "site": "youtube", "cookies": [{}] * 5000}):
        with pytest.raises(ValueError):
            request_for(bad)


def test_extension_cookies_become_jar_entries() -> None:
    raw = [
        {"name": "SAPISID", "value": "s", "domain": ".youtube.com", "path": "/", "secure": True,
         "httpOnly": False, "expirationDate": 1999999999.5, "hostOnly": False},
        {"name": "host", "value": "h", "domain": "www.youtube.com", "hostOnly": True, "session": True},
        {"name": "", "value": "x", "domain": ".youtube.com"},
        {"name": "big", "value": "x" * 9000, "domain": ".youtube.com"},
        "junk",
    ]
    cookies = cookies_from_extension(json.dumps(raw))
    assert [(c.name, c.domain, c.expires, c.include_subdomains) for c in cookies] == [
        ("SAPISID", ".youtube.com", 1999999999, True), ("host", "www.youtube.com", 0, False)]
    assert cookies_from_extension("not json") == []


def test_unknown_extension_is_refused() -> None:
    out = io.BytesIO()
    assert run(["host.exe", "chrome-extension://someone-else/"], io.BytesIO(frame({"type": "ping"})), out) == 1
    assert replies(out.getvalue())[0]["ok"] is False


def test_messages_are_answered_and_delivered() -> None:
    delivered = []
    stdin = io.BytesIO(frame({"type": "ping"}) + frame({"type": "download", "urls": ["https://vimeo.com/1"]})
                       + frame({"type": "bogus"}))
    out = io.BytesIO()
    with patch.object(companion, "ALLOWED_ORIGINS", (ORIGIN,)), \
            patch.object(companion, "deliver", side_effect=lambda request: delivered.append(request) or True):
        assert run(["host.exe", ORIGIN], stdin, out) == 0
    answers = replies(out.getvalue())
    assert answers[0]["ok"] is True and answers[0]["version"]
    assert answers[1] == {"ok": True}
    assert answers[2]["ok"] is False
    assert delivered[0].paths == ("https://vimeo.com/1",)
