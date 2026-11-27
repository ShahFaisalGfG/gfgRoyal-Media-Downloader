"""A stand-in for gallery-dl in tests: it reads the app's command and saves made-up pictures.

The link's first path part picks the scenario, as in fake_ytdlp.py ("https://imgur.com/a/album"
is "a"; for X, "https://x.com/mixed/status/1" is "mixed"). It keeps gallery-dl's behavior that the
app relies on: the "--Print after:" and "--Print skip:" lines with {_path}, the SQLite archive,
the "--filter" that keeps pictures only, the "-J" JSON listing within "--range", and exit status
bits (16 sign-in needed, 64 unsupported).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# Each scenario's files: (name, bytes). Videos are left out by the pictures-only filter.
SCENARIOS = {
    "a": [("album 01.jpg", b"jpg1"), ("album 02.png", b"png2"), ("album 03.gif", b"gif3")],
    "mixed": [("mixed 01.jpg", b"jpg"), ("mixed 02.mp4", b"mp4")],
    "pictures": [("post 01.jpg", b"1"), ("post 02.jpg", b"2"), ("post 03.webp", b"3"), ("post 04.jpg", b"4")],
    "single": [("only.jpg", b"one")],
}


def option(args: list[str], name: str) -> list[str]:
    return [args[index + 1] for index, arg in enumerate(args[:-1]) if arg == name]


def out(text: str) -> None:
    print(text, flush=True)


def err(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def printed(args: list[str], event: str, path: Path) -> None:
    """Print each "--Print EVENT:FORMAT" line with its {_path} filled in."""
    for value in option(args, "--Print"):
        name, _, template = value.partition(":")
        if name == event:
            out(template.replace("{_path}", str(path)))


def archived(archive: Path | None, key: str) -> bool:
    """True when the archive has `key`; else it is added (gallery-dl adds it once the file is saved).
    Without an archive (Download again), nothing was saved before."""
    if archive is None:
        return False
    with sqlite3.connect(archive) as db:
        db.execute("CREATE TABLE IF NOT EXISTS archive (entry TEXT PRIMARY KEY)")
        if db.execute("SELECT 1 FROM archive WHERE entry = ?", (key,)).fetchone():
            return True
        db.execute("INSERT INTO archive VALUES (?)", (key,))
    return False


def main() -> int:
    args = sys.argv[1:]
    state = Path(args[args.index("--fake-state") + 1])
    del args[args.index("--fake-state"):args.index("--fake-state") + 2]
    (state / "gallery-argv.json").write_text(json.dumps(args), encoding="utf-8")
    for isolation in ("--config-ignore", "--no-input"):
        if isolation not in args:
            err(f"[gallery-dl][error] fake gallery-dl refuses a command without {isolation}")
            return 1
    url = args[args.index("--") + 1]
    parts = urlparse(url).path.strip("/").split("/")
    scenario = parts[0] if parts else ""
    images_only = bool(option(args, "--filter"))
    if scenario == "auth":
        err("[twitter][error] AuthRequired: 'username & password' or 'authenticated cookies' needed")
        return 16
    if scenario == "nothing":
        err("[gallery-dl][error] Unsupported URL 'https://fake.test/nothing'")
        return 64
    if scenario == "slow":
        time.sleep(60)
        return 0
    if url.endswith((".jpg", ".png")):
        files = [(Path(urlparse(url).path).name, b"direct")]
    else:
        files = SCENARIOS.get(scenario, [])
    if "-J" in args:
        # The JSON listing: a directory message, then [3, url, details] per file, within --range.
        last = int(option(args, "--range")[0].split("-")[1]) if option(args, "--range") else len(files)
        listed = [(name, data) for name, data in files if not (images_only and name.endswith(".mp4"))][:last]
        messages = [[2, {"category": scenario}]] + [
            [3, f"https://i.fake.test/{name.replace(' ', '_')}",
             {"filename": name.rsplit(".", 1)[0], "extension": name.rsplit(".", 1)[1], "num": index}]
            for index, (name, _data) in enumerate(listed, start=1)]
        out(json.dumps(messages, indent=2))
        return 0
    folder = Path(option(args, "-D")[0])
    archive = Path(option(args, "--download-archive")[0]) if option(args, "--download-archive") else None
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        if images_only and name.endswith(".mp4"):
            continue
        path = folder / name
        if archived(archive, f"{url} {name}"):
            printed(args, "skip", path)
            continue
        path.write_bytes(data)
        printed(args, "after", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
