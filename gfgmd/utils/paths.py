# paths.py - where the app keeps its settings, logs, library, tools, and downloads (stdlib only)
#
# The installed app keeps settings and logs in %APPDATA%\gfgRoyal Media Downloader (small files that
# may roam with the profile) and everything large or machine-specific (the library database, the
# downloaded tools, caches, sign-in data, updates) in %LOCALAPPDATA%\gfgRoyal Media Downloader.
# A portable build keeps both in a "gfgRoyal Media Downloader data" folder next to its exe, falling
# back to the installed locations when that folder can't be written. A build is portable when it
# is the one-file exe, or when gfgRoyal-Media-Downloader-portable.txt sits next to the exe. Running
# from source keeps everything inside the project's build folder, so development never touches an
# installed copy's data. The command-line tool shares the installed app's locations.

import ctypes
import os
import sys
import uuid
from pathlib import Path

APP_FOLDER = "gfgRoyal Media Downloader"
PORTABLE_FOLDER = "gfgRoyal Media Downloader data"
PORTABLE_MARKER = "gfgRoyal-Media-Downloader-portable.txt"
DOWNLOAD_FOLDER = "gfgRoyal Media Downloader"
LEGACY_DOWNLOAD_FOLDER = "youtube-video-downloader"
_UNSET = object()
_data_dir: object = _UNSET
_local_dir: object = _UNSET


def _project_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _from_source() -> bool:
    """True when running from a source checkout (not a frozen build or a pip-installed package)."""
    if getattr(sys, "frozen", False):
        return False
    return os.path.isfile(os.path.join(_project_dir(), "pyproject.toml"))


def appdata_dir() -> str:
    """%APPDATA%\\gfgRoyal Media Downloader, the installed app's settings and logs folder."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_FOLDER)


def localappdata_dir() -> str:
    """%LOCALAPPDATA%\\gfgRoyal Media Downloader, the installed app's machine-specific folder."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_FOLDER)


def is_portable() -> bool:
    """True for a portable build: the one-file exe, or an exe with the portable marker beside it."""
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or bundle is None:
        return False
    if os.path.isfile(os.path.join(_exe_dir(), PORTABLE_MARKER)):
        return True
    return _is_one_file(bundle)


def _exe_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable))


def _is_one_file(bundle: str) -> bool:
    """The one-file exe unpacks to a temp folder; a one-folder build keeps _internal beside the exe."""
    return os.path.normcase(os.path.dirname(os.path.abspath(bundle))) != os.path.normcase(_exe_dir())


def data_dir() -> str | None:
    """The folder for settings and logs, created if needed; None when running from source."""
    global _data_dir
    if _data_dir is _UNSET:
        _data_dir = _resolve_data()
    return _data_dir  # type: ignore[return-value]


def _resolve_data() -> str | None:
    if _from_source():
        return None
    portable = _portable_folder()
    if portable:
        return portable
    return _ensure(appdata_dir())


def local_dir() -> str:
    """The folder for the library, tools, caches, sign-ins, and updates, created if needed."""
    global _local_dir
    if _local_dir is _UNSET:
        _local_dir = _resolve_local()
    return _local_dir  # type: ignore[return-value]


def _resolve_local() -> str:
    if _from_source():
        return _ensure(os.path.join(_project_dir(), "build", "local"))
    portable = _portable_folder()
    if portable:
        return portable
    return _ensure(localappdata_dir())


def _portable_folder() -> str | None:
    if not is_portable():
        return None
    folder = os.path.join(_exe_dir(), PORTABLE_FOLDER)
    return folder if _writable(folder) else None


def local_subdir(name: str) -> Path:
    """A named folder under local_dir() (tools, cache, signins, run, thumbnails), created if needed."""
    folder = Path(local_dir()) / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def tools_dir() -> Path:
    """Where the managed copies of yt-dlp, FFmpeg, and Deno live."""
    return local_subdir("tools")


def cache_dir() -> Path:
    """yt-dlp's cache (player signatures and challenge results)."""
    return local_subdir("cache")


def updates_dir() -> str:
    """Where downloaded app updates wait to be installed (the shared updater's folder)."""
    if _from_source():
        return os.path.join(_project_dir(), "build", "updates")
    return str(local_subdir("updates"))


# Windows' known-folder IDs for the user's Videos and Music folders.
_FOLDER_IDS = {"Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC", "Music": "4BD8D571-6D19-48D3-BE97-422220080E43"}


def known_folder(name: str) -> Path:
    """The user's Videos or Music folder, wherever Windows keeps it (moved or synced); else ~/<name>."""
    if sys.platform == "win32":
        guid = uuid.UUID(_FOLDER_IDS[name])
        buffer = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        try:
            folder_id = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
            if shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(buffer)) == 0 and buffer.value:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass  # fall back to the home folder below
        finally:
            if buffer.value is not None:
                ole32.CoTaskMemFree(buffer)
    return Path.home() / name


def default_download_root() -> Path:
    """Videos\\gfgRoyal Media Downloader, or the original script's folder when it exists and the new one doesn't."""
    videos = known_folder("Videos")
    current = videos / DOWNLOAD_FOLDER
    legacy = videos / LEGACY_DOWNLOAD_FOLDER
    if not current.exists() and (legacy / ".archives").is_dir():
        return legacy
    return current


def default_audio_root() -> Path:
    """Music\\gfgRoyal Media Downloader: where audio downloads go unless the user picks a folder."""
    return known_folder("Music") / DOWNLOAD_FOLDER


def _ensure(folder: str) -> str:
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass  # reported later by whoever fails to write there
    return folder


def _writable(folder: str) -> bool:
    """Create folder if needed and check a file can be written in it."""
    probe = os.path.join(folder, ".write-test")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(probe, "w", encoding="utf-8"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False
