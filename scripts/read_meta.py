"""Output app metadata from pyproject.toml as JSON on stdout."""
import json
import pathlib
import tomllib

_toml = pathlib.Path(__file__).parent.parent / "pyproject.toml"

with _toml.open("rb") as _fh:
    _data = tomllib.load(_fh)

_project = _data["project"]
_app = _data.get("tool", {}).get("gfgmd", {})

print(json.dumps({
    "Version":   _project["version"],
    "AppName":   _app.get("display_name", "gfgRoyal Media Downloader"),
    "FileName":  _app.get("file_name", "gfgRoyal-Media-Downloader"),
    "Publisher": _app.get("publisher", "gfgRoyal"),
    "Url":       _app.get("url", ""),
    "ExeName":   _app.get("exe_name", "gfgRoyal-Media-Downloader.exe"),
    "WingetId":  _app.get("winget_id", ""),
}))
