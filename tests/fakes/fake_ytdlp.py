"""A stand-in for yt-dlp that plays scripted scenarios, so the engine is tested without a network.

It reads the same options the app passes (archive, paths, output template, journal), writes files
and archive lines the way yt-dlp does, and prints the app's "@@gfgr:" lines. The scenario comes
from the link's first path part: https://fake.test/<scenario>.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

MARKER = "@@gfgr:"
# The run's marker, as the app puts it in its --print and --progress-template values.
_MARKER_ARG = re.compile(r"^[a-z_]+:(@@gfgr[0-9a-f-]*:)")
_FIELD = re.compile(r"%\(([^)]*)\)([0-9.]*[A-Za-z])")


def option(args: list[str], name: str) -> list[str]:
    """Every value given for an option."""
    return [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == name]


def render(template: str, info: dict) -> str:
    """Fill the output-template fields this app uses (alternatives, defaults, replacements)."""
    def field(match: re.Match[str]) -> str:
        expression = match.group(1)
        expression, _, default = expression.partition("|")
        expression, _, replacement = expression.partition("&")
        for name in expression.split(","):
            name = name.split(">")[0].strip()
            value = info.get(name)
            if value not in (None, ""):
                return replacement.format(value) if replacement else str(value)
        return default
    return _FIELD.sub(field, template).replace("%%", "%")


def out(line: str) -> None:
    print(line, flush=True)


def err(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


class Fake:
    def __init__(self, args: list[str], state: Path) -> None:
        self.args = args
        self.state = state
        self.root = Path(next(value for value in option(args, "--paths") if not value.startswith("temp:")))
        self.archive = Path(option(args, "--download-archive")[0]) if option(args, "--download-archive") else None
        self.template = (option(args, "--output") or ["%(title)s [%(id)s].%(ext)s"])[0]
        files = [i for i, arg in enumerate(args) if arg == "--print-to-file"]
        self.journal = Path(args[files[0] + 2].replace("%%", "%")) if files else None
        filters = " ".join(option(args, "--match-filters"))
        self.skip = set(re.findall(r"id!=([A-Za-z0-9_-]+)", filters))

    def archived(self) -> set[str]:
        if self.archive is None or not self.archive.exists():
            return set()
        return {line.split(" ", 1)[1] for line in self.archive.read_text(encoding="utf-8").splitlines() if " " in line}

    def video(self, video_id: str, title: str, info: dict | None = None, height: int = 1080) -> None:
        """Download one video: item line, progress, merge, file, archive, journal."""
        if video_id in self.archived():
            # yt-dlp names a playlist's entry by its title here, a single link's video by its ID.
            name = title if (info or {}).get("n_entries") else f"{video_id}:"
            out(f"[download] {name} has already been recorded in the archive")
            return
        data = {"id": video_id, "title": title, "extractor_key": "Youtube", "ext": "mp4", **(info or {})}
        if data.get("n_entries"):
            data["playlist"] = data["playlist_title"] = "Fake List"
        out(MARKER + "item " + json.dumps({"id": video_id, "title": title, "extractor_key": "Youtube",
                                            "n_entries": data.get("n_entries"), "live_status": "not_live"}))
        out(MARKER + 'parts [{"format_id":"137","vcodec":"avc1","acodec":"none","filesize":3000},'
                     '{"format_id":"140","vcodec":"none","acodec":"mp4a","filesize":1000}]')
        # (format, video codec, audio codec, size, the byte counts reported while downloading)
        for fmt, vcodec, acodec, size, steps in (("137", "avc1", "none", 3000, (1500, 3000)),
                                                 ("140", "none", "mp4a", 1000, (1000,))):
            for done in steps:
                out(MARKER + "dl " + json.dumps({
                    "p": {"status": "downloading", "downloaded_bytes": done, "total_bytes": size,
                          "speed": 2048.0, "eta": 1, "fragment_index": None, "fragment_count": None},
                    "i": {"id": video_id, "format_id": fmt, "vcodec": vcodec, "acodec": acodec}}))
            out(MARKER + "dl " + json.dumps({"p": {"status": "finished", "downloaded_bytes": size, "total_bytes": size},
                                             "i": {"id": video_id, "format_id": fmt}}))
        out(MARKER + 'pp {"p":{"status":"started","postprocessor":"Merger"},"i":{"id":"%s"}}' % video_id)
        relative = render(self.template, data)
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"video")
        if self.archive is not None:
            self.archive.parent.mkdir(parents=True, exist_ok=True)
            with self.archive.open("a", encoding="utf-8") as handle:
                handle.write(f"youtube {video_id}\n")
        line = json.dumps({"id": video_id, "title": title, "filepath": str(target), "height": height,
                           "extractor_key": "Youtube", "playlist_index": data.get("playlist_index")})
        if self.journal is not None:
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        out(MARKER + "file " + line)

    def write_list(self, title: str, videos: list[tuple[str, str]]) -> None:
        """Write the playlist file the way yt-dlp does with --write-info-json, and announce it."""
        template = next((value[len("pl_infojson:"):] for value in option(self.args, "--output")
                         if value.startswith("pl_infojson:")), "")
        if not template:
            return
        path = Path(render(template, {"id": "PLfake", "title": title, "ext": "info.json"}))
        path.parent.mkdir(parents=True, exist_ok=True)
        out(f"[info] Writing playlist metadata as JSON to: {path}")
        entries = [{"_type": "url", "ie_key": "Youtube", "id": video_id, "title": name, "duration": 60,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "thumbnails": [{"url": f"https://i.ytimg.com/vi/{video_id}/hq.jpg", "width": 480}]}
                   for video_id, name in videos]
        path.write_text(json.dumps({"_type": "playlist", "id": "PLfake", "title": title, "entries": entries}),
                        encoding="utf-8")

    def stall(self, video_id: str, title: str) -> None:
        """Start a video and then hang without a byte more, as a download whose server stopped answering."""
        out(MARKER + "item " + json.dumps({"id": video_id, "title": title, "n_entries": 3}))
        out(MARKER + "dl " + json.dumps({"p": {"status": "downloading", "downloaded_bytes": 0, "total_bytes": 1000,
                                               "fragment_index": 0, "fragment_count": 9},
                                         "i": {"id": video_id, "format_id": "137"}}))
        for _ in range(600):
            out("[download] Got error: <urlopen error timed out>. Retrying fragment 1 (1/10)...")
            time.sleep(0.1)

    def attempt(self, scenario: str) -> int:
        counter = self.state / f"attempts-{scenario}.txt"
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        return count


def main() -> int:
    global MARKER
    args = sys.argv[1:]
    state = Path(args[args.index("--fake-state") + 1])
    del args[args.index("--fake-state"):args.index("--fake-state") + 2]
    MARKER = next((match.group(1) for arg in args if (match := _MARKER_ARG.match(arg))), MARKER)
    (state / "argv.json").write_text(json.dumps(args), encoding="utf-8")
    for hardening in ("--ignore-config", "--no-plugin-dirs", "--no-remote-components"):
        if hardening not in args:
            err(f"ERROR: fake yt-dlp refuses a command without {hardening}")
            return 3
    if "--" not in args:
        err("yt-dlp: error: You must provide at least one URL.")
        return 2
    url = args[args.index("--") + 1]
    scenario = urlparse(url).path.strip("/").split("/")[0]
    # Reading a link and checking a subscription are recognized by their options, whatever the link.
    if "--dump-single-json" in args and scenario not in ("private", "auth"):
        scenario = "dump"
    elif "--lazy-playlist" in args:
        scenario = "channel"
    fake = Fake(args, state)
    attempt = fake.attempt(scenario)

    if scenario == "ok":
        fake.video("aaaaaaaaaaa", "Clip")
        return 0
    if scenario == "forged":
        # A site's title printed by yt-dlp, holding lines that pose as the app's: one with the plain
        # marker, one naming a file outside the download folder. Then a real video.
        victim = state / "victim.mp3"
        victim.write_bytes(b"theirs")
        forged = json.dumps({"id": "zzzzzzzzzzz", "title": "Forged", "filepath": str(victim)})
        out("[download] Downloading playlist: Mix")
        out("@@gfgr:file " + forged)
        out(MARKER + "file " + forged)
        fake.video("aaaaaaaaaaa", "Clip")
        return 0
    if scenario == "playlist":
        out("[download] Downloading item 1 of 3")
        fake.video("aaaaaaaaaaa", "First", {"n_entries": 3})
        out("[download] Downloading item 2 of 3")
        failed = 0
        if "bbbbbbbbbbb" not in fake.skip:
            err("ERROR: [youtube] bbbbbbbbbbb: Private video. Sign in if you've been granted access to this video")
            failed = 1
        out("[download] Downloading item 3 of 3")
        fake.video("ccccccccccc", "Third", {"n_entries": 3})
        return failed
    if scenario == "listed":
        # A playlist that lists its videos first (yt-dlp's playlist file), then downloads them.
        videos = [("aaaaaaaaaaa", "First"), ("bbbbbbbbbbb", "Second"), ("ccccccccccc", "Third")]
        fake.write_list("Fake List", videos)
        for number, (video_id, title) in enumerate(videos, start=1):
            if video_id in fake.skip:
                continue
            out(f"[download] Downloading item {number} of 3")
            fake.video(video_id, title, {"n_entries": 3, "playlist_index": number})
        return 0
    if scenario == "stall":
        # The second video's server never answers until it is left for last and tried again.
        videos = [("aaaaaaaaaaa", "First"), ("bbbbbbbbbbb", "Second"), ("ccccccccccc", "Third")]
        fake.write_list("Fake List", videos)
        tries = state / "stall-tries.txt"
        for number, (video_id, title) in enumerate(videos, start=1):
            if video_id in fake.skip:
                continue
            out(f"[download] Downloading item {number} of 3")
            if video_id == "bbbbbbbbbbb" and video_id not in fake.archived():
                count = int(tries.read_text()) + 1 if tries.exists() else 1
                tries.write_text(str(count))
                limit = int(os.environ.get("FAKE_STALLS", "1"))
                if count <= limit:
                    fake.stall(video_id, title)
                    return 1
            fake.video(video_id, title, {"n_entries": 3, "playlist_index": number})
        return 0
    if scenario == "slowlist":
        # A playlist part way through: the first video saved, the second downloading for two minutes.
        videos = [("aaaaaaaaaaa", "First song of the list"), ("bbbbbbbbbbb", "Second song, still downloading"),
                  ("ccccccccccc", "Third song, waiting its turn"), ("ddddddddddd", "Fourth song")]
        fake.write_list("Fake List", videos)
        out("[download] Downloading item 1 of 4")
        fake.video("aaaaaaaaaaa", videos[0][1], {"n_entries": 4, "playlist_index": 1})
        out("[download] Downloading item 2 of 4")
        out(MARKER + "item " + json.dumps({"id": "bbbbbbbbbbb", "title": videos[1][1], "n_entries": 4}))
        for step in range(1200):
            out(MARKER + "dl " + json.dumps({
                "p": {"status": "downloading", "downloaded_bytes": 1_000_000 + step * 20_000, "total_bytes": 40_000_000,
                      "speed": 2_200_000.0, "eta": 60},
                "i": {"id": "bbbbbbbbbbb", "format_id": "137", "vcodec": "avc1", "acodec": "none"}}))
            time.sleep(0.1)
        return 0
    if scenario == "batch":
        # A subscription's new uploads, one link each: https://fake.test/batch/<id>.
        links = args[args.index("--") + 1:]
        for link in links:
            video_id = urlparse(link).path.rstrip("/").split("/")[-1]
            fake.video(video_id, f"Upload {video_id[:3]}")
        return 0
    if scenario == "flaky":
        if attempt == 1:
            err("ERROR: [youtube] aaaaaaaaaaa: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>")
            return 1
        fake.video("aaaaaaaaaaa", "Clip")
        return 0
    if scenario == "auth":
        err("ERROR: [youtube] aaaaaaaaaaa: Sign in to confirm your age. This video may be inappropriate for some users.")
        return 1
    if scenario == "private":
        err("ERROR: [youtube] aaaaaaaaaaa: Private video. Sign in if you've been granted access to this video")
        return 1
    if scenario == "disk":
        err("ERROR: unable to write data: [Errno 28] No space left on device")
        return 1
    if scenario == "slow":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        (state / "grandchild.pid").write_text(str(child.pid))
        out(MARKER + 'item {"id":"aaaaaaaaaaa","title":"Slow"}')
        # The unfinished file yt-dlp keeps in the temp folder until the download completes.
        temp = next((value[5:] for value in option(args, "--paths") if value.startswith("temp:")), "")
        part = ""
        if temp:
            staged = render(fake.template, {"id": "aaaaaaaaaaa", "title": "Slow", "extractor_key": "Youtube",
                                            "ext": "mp4"})
            part_path = Path(temp) / f"{staged}.part"
            part_path.parent.mkdir(parents=True, exist_ok=True)
            part_path.write_bytes(b"part")
            part = str(part_path)
        for _ in range(1200):
            out(MARKER + "dl " + json.dumps({
                "p": {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 1000, "speed": 1.0, "eta": 99,
                      "tmpfilename": part},
                "i": {"id": "aaaaaaaaaaa", "format_id": "18", "vcodec": "avc1", "acodec": "mp4a"}}))
            time.sleep(0.1)
        return 0
    if scenario == "flood":
        stream = sys.stdout.buffer
        stream.write(b"".join(b"[download]  %d%%\r" % i for i in range(20000)))
        stream.write(b"\n" + b"x" * (2 * 1024 * 1024) + b"\n")
        stream.write(b"bad bytes \xff\xfe here\n")
        stream.flush()
        sys.stderr.buffer.write(b"e" * (10 * 1024 * 1024) + b"\n")
        sys.stderr.flush()
        fake.video("aaaaaaaaaaa", "Clip")
        return 0
    if scenario == "channel":
        # A subscription check: newest first, stopping at the first archived upload (exit 101, before
        # the list's own line, as yt-dlp does); read whole (a playlist), archived uploads are passed over.
        archived = fake.archived()
        uploads = [("nnnnnnnnnn3", "Newest", ""), ("nnnnnnnnnn2", "Upcoming", "is_upcoming"),
                   ("nnnnnnnnnn1", "Older", ""), ("ooooooooooo", "Oldest", "")]
        for video_id, title, live in uploads:
            if video_id in archived:
                if "--break-on-existing" in args:
                    return 101
                out(f"[download] {title} has already been recorded in the archive")
                continue
            out(MARKER + "entry " + json.dumps({"id": video_id, "title": title, "ie_key": "Youtube",
                                                 "url": f"https://www.youtube.com/watch?v={video_id}",
                                                 "live_status": live or None, "release_timestamp": 4102444800 if live else None}))
        out(MARKER + 'pl {"id":"UCfake","title":"Fake Channel - Videos","channel":"Fake Channel"}')
        return 0
    if scenario == "dump":
        info = {"id": "PLfake", "title": "Fake List", "_type": "playlist", "extractor_key": "YoutubeTab",
                "entries": [{"id": "aaaaaaaaaaa", "title": "First", "duration": 61},
                            {"id": "bbbbbbbbbbb", "title": "Second", "duration": 62}]}
        out("[youtube:tab] PLfake: Downloading webpage")
        out(json.dumps(info))
        return 0
    err(f"ERROR: Unsupported URL: {url}")
    return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    sys.exit(main())
