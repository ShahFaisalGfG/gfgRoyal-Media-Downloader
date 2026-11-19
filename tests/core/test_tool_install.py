"""Managed tool installs: checksums, resumed downloads, safe unpacking, manifests, and rollback.

An in-memory stand-in for GitHub serves the files, so nothing is downloaded.
"""

import hashlib
import io
import urllib.error
import zipfile
from pathlib import Path

import pytest

from gfgmd.core import tool_install
from gfgmd.core.tool_install import (
    Package,
    ToolInstallError,
    check_url,
    download,
    install,
    parse_checksums,
    remove_unused,
    rollback,
    safe_extract,
)
from gfgmd.core.tools import managed_tools, read_manifest

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
    """Treat every unpacked program as working (the test zips hold no real executables)."""
    monkeypatch.setattr(tool_install, "tool_version", lambda name, path: "9.9.9")


def package() -> Package:
    return Package("deno", "Deno", BASE, "SUMS", (r"deno-win\.zip",), {"deno": "deno.exe"}, 1)


def test_check_url_allows_only_github_https() -> None:
    check_url("https://github.com/x")
    check_url("https://release-assets.githubusercontent.com/x")
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
    with pytest.raises(ToolInstallError, match="checksum"):
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
