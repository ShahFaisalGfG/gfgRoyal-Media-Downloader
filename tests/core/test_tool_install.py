"""Managed tool installs: checksums, resumed downloads, safe unpacking, manifests, and rollback.

An in-memory stand-in for GitHub serves the files, so nothing is downloaded.
"""

import errno
import hashlib
import io
import json
import os
import threading
import urllib.error
import zipfile
from pathlib import Path

import pytest

from gfgmd.core import tool_install
from gfgmd.core.tool_install import (
    Package,
    ToolDownloadError,
    ToolInstallCancelled,
    ToolInstallError,
    ToolStartError,
    ToolVerifyError,
    check_url,
    download,
    install,
    parse_checksums,
    remove_unused,
    rollback,
    safe_extract,
)
from gfgmd.core.tools import ToolsMissing, managed_tools, path_tools, read_manifest, resolve_tools

BASE = "https://github.com/owner/repo/releases/latest/download/"


class Response(io.BytesIO):
    def __init__(self, data: bytes, url: str, status: int = 200) -> None:
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}
        self._url = url
        self.redirect_chain = [url.replace("/latest/download/", "/download/v9.9.9/")]

    def geturl(self) -> str:
        return self._url


class Server:
    """Serves files by URL and honors Range requests."""

    def __init__(self, files: dict[str, bytes], honor_range: bool = True) -> None:
        self.files = files
        self.honor_range = honor_range
        self.requests: list[tuple[str, dict | None]] = []

    def __call__(self, url: str, headers: dict | None) -> Response:
        self.requests.append((url, headers))
        name = url.rsplit("/", 1)[-1]
        if name not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        data = self.files[name]
        if headers and "Range" in headers and self.honor_range:
            start = int(headers["Range"].split("=")[1].rstrip("-"))
            return Response(data[start:], url, 206)
        return Response(data, url)


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def runs_anywhere(monkeypatch):
    """Treat every unpacked program as working (the test zips hold placeholder bytes, not programs)."""
    monkeypatch.setattr(tool_install, "tool_version", lambda name, path: "9.9.9")


def package() -> Package:
    return Package("deno", "Deno", BASE, "SUMS", (r"deno-win\.zip",), {"deno": "deno.exe"}, 1)


def test_check_url_allows_only_the_release_hosts_over_https() -> None:
    check_url("https://github.com/x")
    check_url("https://release-assets.githubusercontent.com/x")
    check_url("https://api.github.com/repos/x/y/releases/latest")
    check_url("https://codeberg.org/x/y/releases/download/v1/gallery-dl.exe")
    for bad in ("http://github.com/x", "https://evil.example/x", "https://github.com.evil.example/x", "file:///c:/x"):
        with pytest.raises(ToolInstallError):
            check_url(bad)


def test_parse_checksums() -> None:
    text = f"{'a' * 64}  yt-dlp.exe\n{'B' * 64} *yt-dlp_win.zip\nnot a line\n"
    assert parse_checksums(text) == {"yt-dlp.exe": "a" * 64, "yt-dlp_win.zip": "b" * 64}


def test_download_verifies_and_resumes(tmp_path: Path) -> None:
    data = b"x" * 1_000_000
    server = Server({"pkg.zip": data})
    target = tmp_path / "pkg.zip"
    part = target.with_name("pkg.zip.part")
    part.write_bytes(data[:400_000])
    download(BASE + "pkg.zip", target, sha(data), opener=server)
    assert target.read_bytes() == data and not part.exists()
    assert server.requests[0][1] == {"Range": "bytes=400000-"}


def test_download_restarts_when_range_is_ignored(tmp_path: Path) -> None:
    data = b"y" * 300_000
    target = tmp_path / "pkg.zip"
    target.with_name("pkg.zip.part").write_bytes(b"stale")
    download(BASE + "pkg.zip", target, sha(data), opener=Server({"pkg.zip": data}, honor_range=False))
    assert target.read_bytes() == data


def test_checksum_mismatch_deletes_the_file(tmp_path: Path) -> None:
    target = tmp_path / "pkg.zip"
    with pytest.raises(ToolVerifyError, match="checksum"):
        download(BASE + "pkg.zip", target, "0" * 64, opener=Server({"pkg.zip": b"tampered"}))
    assert not target.exists() and not target.with_name("pkg.zip.part").exists()


def test_size_limit(tmp_path: Path) -> None:
    with pytest.raises(ToolInstallError, match="larger"):
        download(BASE + "pkg.zip", tmp_path / "pkg.zip", sha(b"z" * 100), opener=Server({"pkg.zip": b"z" * 100}),
                 limit=10)


@pytest.mark.parametrize("name", ["../evil.exe", "/abs/evil.exe", "C:/evil.exe", "a/../../evil.exe"])
def test_unsafe_zip_paths_are_refused(name: str, tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    archive.write_bytes(make_zip({name: b"evil"}))
    with pytest.raises(ToolInstallError, match="unsafe"):
        safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "evil.exe").exists()


def test_install_switch_rollback_and_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    first = make_zip({"deno.exe": b"one"})
    server = Server({"SUMS": f"{sha(first)}  deno-win.zip\n".encode(), "deno-win.zip": first})
    entries = install(package(), root, opener=server)
    assert entries["deno"]["version"] == "9.9.9" and entries["deno"]["tag"] == "v9.9.9"
    first_path = managed_tools(root)["deno"]
    assert Path(first_path).read_bytes() == b"one"

    second = make_zip({"deno.exe": b"two"})
    server.files = {"SUMS": f"{sha(second)}  deno-win.zip\n".encode(), "deno-win.zip": second}
    install(package(), root, opener=server)
    assert Path(managed_tools(root)["deno"]).read_bytes() == b"two"
    assert read_manifest(root)["deno"]["previous"]["sha256"] == sha(first)

    assert rollback(root, ("deno",))
    assert Path(managed_tools(root)["deno"]).read_bytes() == b"one"
    remove_unused(root)
    assert len(list((root / "deno").iterdir())) == 1
    assert not (root / ".staging").exists()


CODEBERG_API = "https://codeberg.org/api/v1/repos/mikf/gallery-dl/releases/latest"
GITHUB_API = "https://api.github.com/repos/spotDL/spotify-downloader/releases/latest"


def release_json(tag: str, files: dict[str, str], digests: dict[str, str] | None = None) -> bytes:
    """A forge's latest-release answer listing these files at these links (and GitHub's digests)."""
    assets = [{"name": name, "browser_download_url": url,
               **({"digest": f"sha256:{digests[name]}"} if digests and name in digests else {})}
              for name, url in files.items()]
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def gallery_package() -> Package:
    return Package("gallery-dl", "gallery-dl", "", "SHA256SUMS", (r"gallery-dl\.exe",),
                   {"gallery-dl": "gallery-dl.exe"}, 1, release_api=CODEBERG_API, bare_exe=True)


def spotdl_package() -> Package:
    return Package("spotdl", "spotDL", "", "", (r"spotdl-[0-9.]+-win32\.exe",), {"spotdl": "spotdl.exe"}, 1,
                   release_api=GITHUB_API, bare_exe=True)


def test_a_codeberg_release_installs_its_program_file(tmp_path: Path) -> None:
    """gallery-dl: the release API names the files, SHA256SUMS gives the hash, the exe is the program."""
    root = tmp_path / "tools"
    base = "https://codeberg.org/mikf/gallery-dl/releases/download/v1.32.21/"
    for program in (b"first build", b"second build"):
        sums = f"{sha(b'linux')}  gallery-dl.bin\n{sha(program)}  gallery-dl.exe\n".encode()
        server = Server({"latest": release_json("v1.32.21", {name: base + name for name in
                                                             ("gallery-dl.bin", "gallery-dl.exe", "SHA256SUMS")}),
                         "SHA256SUMS": sums, "gallery-dl.exe": program})
        entries = install(gallery_package(), root, opener=server)
    assert entries["gallery-dl"]["tag"] == "v1.32.21" and entries["gallery-dl"]["sha256"] == sha(b"second build")
    assert Path(managed_tools(root)["gallery-dl"]).name == "gallery-dl.exe"
    assert Path(managed_tools(root)["gallery-dl"]).read_bytes() == b"second build"
    assert [url for url, _ in server.requests] == [CODEBERG_API, base + "SHA256SUMS", base + "gallery-dl.exe"]
    stale = root / "gallery-dl" / "v1.0.0-00000000"
    stale.mkdir()
    remove_unused(root)  # the folders of programs beyond yt-dlp, FFmpeg, and Deno are tidied too
    assert not stale.exists() and len(list((root / "gallery-dl").iterdir())) == 2  # current and previous


def test_a_github_release_without_sums_uses_the_hash_github_records(tmp_path: Path) -> None:
    """spotDL: GitHub's per-file SHA-256 checks the download; the program takes the name the app runs."""
    root = tmp_path / "tools"
    program = b"spotdl build"
    link = "https://github.com/spotDL/spotify-downloader/releases/download/v4.6.0/spotdl-4.6.0-win32.exe"
    listing = release_json("v4.6.0", {"spotdl-4.6.0-darwin": link[:-9] + "darwin", "spotdl-4.6.0-win32.exe": link},
                           {"spotdl-4.6.0-win32.exe": sha(program)})
    install(spotdl_package(), root, opener=Server({"latest": listing, "spotdl-4.6.0-win32.exe": program}))
    assert Path(managed_tools(root)["spotdl"]).name == "spotdl.exe"
    tampered = Server({"latest": listing, "spotdl-4.6.0-win32.exe": b"something else"})
    with pytest.raises(ToolVerifyError, match="checksum"):
        install(spotdl_package(), tmp_path / "other", opener=tampered)


def test_a_release_without_a_hash_or_off_the_release_hosts_is_refused(tmp_path: Path) -> None:
    link = "https://github.com/spotDL/spotify-downloader/releases/download/v4.6.0/spotdl-4.6.0-win32.exe"
    unhashed = Server({"latest": release_json("v4.6.0", {"spotdl-4.6.0-win32.exe": link})})
    with pytest.raises(ToolVerifyError, match="no SHA-256"):
        install(spotdl_package(), tmp_path / "a", opener=unhashed)
    elsewhere = Server({"latest": release_json("v4.6.0", {"spotdl-4.6.0-win32.exe": "https://evil.example/spotdl.exe"},
                                               {"spotdl-4.6.0-win32.exe": "a" * 64})})
    with pytest.raises(ToolVerifyError, match="Refused"):
        install(spotdl_package(), tmp_path / "b", opener=elsewhere)
    unreadable = Server({"latest": b"<html>not json</html>"})
    with pytest.raises(ToolVerifyError, match="can't be read"):
        install(spotdl_package(), tmp_path / "c", opener=unreadable)


def test_gallery_dl_and_spotdl_are_extras_downloads_run_without(tmp_path: Path, monkeypatch) -> None:
    """Only yt-dlp, FFmpeg, ffprobe, and Deno are required; an extra that is found is used."""
    monkeypatch.setenv("PATH", "")
    root = tmp_path / "tools"
    for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno", "gallery-dl"):
        (root / name).mkdir(parents=True)
        (root / name / f"{name}.exe").write_bytes(b"x")
    tool_install.write_manifest(root, {name: {"path": f"{name}/{name}.exe"}
                                       for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno", "gallery-dl")})
    tools = resolve_tools("managed", root)
    assert tools.gallery_dl.endswith("gallery-dl.exe") and tools.spotdl == ""
    (root / "deno" / "deno.exe").unlink()
    with pytest.raises(ToolsMissing) as missing:
        resolve_tools("managed", root)
    assert missing.value.missing == ["deno"]


def test_install_refuses_a_package_without_the_program(tmp_path: Path) -> None:
    bundle = make_zip({"readme.txt": b"no exe"})
    server = Server({"SUMS": f"{sha(bundle)}  deno-win.zip\n".encode(), "deno-win.zip": bundle})
    with pytest.raises(ToolInstallError, match="no deno.exe"):
        install(package(), tmp_path / "tools", opener=server)
    assert read_manifest(tmp_path / "tools") == {}


def test_missing_asset_is_reported(tmp_path: Path) -> None:
    server = Server({"SUMS": f"{'a' * 64}  something-else.zip\n".encode()})
    with pytest.raises(ToolInstallError, match="no Windows build"):
        install(package(), tmp_path / "tools", opener=server)


def test_a_dropped_connection_is_a_download_error(tmp_path: Path) -> None:
    def offline(url: str, headers: dict | None) -> Response:
        raise urllib.error.URLError("getaddrinfo failed")

    with pytest.raises(ToolDownloadError, match="getaddrinfo"):
        download(BASE + "pkg.zip", tmp_path / "pkg.zip", sha(b"x"), opener=offline)


def test_a_full_drive_is_not_reported_as_a_connection_problem(tmp_path: Path) -> None:
    def full(url: str, headers: dict | None) -> Response:
        raise OSError(errno.ENOSPC, "No space left on device")

    with pytest.raises(OSError) as raised:
        download(BASE + "pkg.zip", tmp_path / "pkg.zip", sha(b"x"), opener=full)
    assert not isinstance(raised.value, ToolInstallError)


def test_cancel_stops_the_download(tmp_path: Path) -> None:
    stop = threading.Event()
    stop.set()
    with pytest.raises(ToolInstallCancelled):
        download(BASE + "pkg.zip", tmp_path / "pkg.zip", sha(b"x"), cancel=stop, opener=Server({"pkg.zip": b"x"}))


def test_a_program_that_doesnt_run_names_its_package(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tool_install, "tool_version", lambda name, path: "")
    bundle = make_zip({"deno.exe": b"blocked"})
    server = Server({"SUMS": f"{sha(bundle)}  deno-win.zip\n".encode(), "deno-win.zip": bundle})
    with pytest.raises(ToolStartError) as raised:
        install(package(), tmp_path / "tools", opener=server)
    assert raised.value.label == "Deno"


def test_install_starts_each_program_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check that a program works also reads its version for the manifest (gallery-dl and spotDL
    unpack themselves on every start, so each extra start costs seconds)."""
    started: list[str] = []
    monkeypatch.setattr(tool_install, "tool_version", lambda name, path: started.append(path) or "2.9.8")
    bundle = make_zip({"deno.exe": b"one"})
    server = Server({"SUMS": f"{sha(bundle)}  deno-win.zip\n".encode(), "deno-win.zip": bundle})
    entries = install(package(), tmp_path / "tools", opener=server)
    assert entries["deno"]["version"] == "2.9.8" and read_manifest(tmp_path / "tools")["deno"]["version"] == "2.9.8"
    assert len(started) == 1


def test_install_reports_its_steps_in_plain_words(tmp_path: Path) -> None:
    bundle = make_zip({"deno.exe": b"one"})
    server = Server({"SUMS": f"{sha(bundle)}  deno-win.zip\n".encode(), "deno-win.zip": bundle})
    stages: list[str] = []
    install(package(), tmp_path / "tools", progress=lambda stage, done, total: stages.append(stage), opener=server)
    assert list(dict.fromkeys(stages)) == ["Looking for the newest version", "Downloading", "Unpacking",
                                           "Checking that it works", "Done"]


@pytest.mark.skipif(os.name != "nt", reason="Windows looks in the current folder for programs")
def test_tools_are_never_taken_from_the_current_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A yt-dlp.exe or ffprobe.bat dropped where the command line runs isn't used as the tool."""
    here = tmp_path / "Downloads"
    here.mkdir()
    for planted in ("yt-dlp.exe", "ffprobe.bat", "ffmpeg.cmd"):
        (here / planted).write_bytes(b"")
    monkeypatch.chdir(here)
    monkeypatch.setenv("PATH", ";" + str(tmp_path / "empty") + ";.")  # an empty and a relative entry
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    assert path_tools() == {}
