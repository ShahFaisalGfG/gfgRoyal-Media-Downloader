# recycle.py - move files to the Recycle Bin (never a permanent delete)

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path

from gfgmd.core.captions import companion_files
from gfgmd.core.naming import remove_empty_folders
from gfgmd.utils.logging import write_log

_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400


class _FileOp(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def to_recycle_bin(paths: list[str]) -> bool:
    """Send existing files to the Recycle Bin in one operation; True when Windows did it."""
    existing = [os.path.abspath(path) for path in paths if os.path.isfile(path)]
    if not existing or sys.platform != "win32":
        return False
    operation = _FileOp()
    operation.wFunc = _FO_DELETE
    operation.pFrom = "\0".join(existing) + "\0\0"
    operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted:
        # The code is Windows' reason, for the log (0x20, a sharing violation, means the file is open somewhere).
        write_log(f"Windows couldn't move {len(existing)} file(s) to the Recycle Bin (code {result:#x}), "
                  f"first {existing[0]}", "critical")
        return False
    return True


def recycle_media(paths: list[str]) -> list[str]:
    """Send media files, with the captions, lyrics, and covers saved beside them, to the Recycle Bin.

    Returns the media files Windows couldn't move (open in another program, say); files no longer
    there count as moved. All go in one operation; when Windows stops partway, what is left goes one
    file at a time, which finds the ones it can't move.
    """
    groups = {path: [path, *(str(entry) for entry in companion_files(Path(path)))]
              for path in dict.fromkeys(paths) if os.path.isfile(path)}
    if not groups or to_recycle_bin([entry for group in groups.values() for entry in group]):
        return []
    return [path for path, group in groups.items()
            if os.path.isfile(path) and not to_recycle_bin([entry for entry in group if os.path.exists(entry)])]


def recycle_saved(files: Sequence[tuple[str, Path | None]]) -> list[str]:
    """Send downloaded files to the Recycle Bin (see recycle_media), then remove the playlist and
    channel folders they leave empty.

    Each file comes with the download folder it was saved under, which stays, as does every folder
    above it; a file without one (None) keeps its folder. Returns the files Windows couldn't move.
    """
    failed = recycle_media([path for path, _ in files])
    emptied: dict[Path, set[Path]] = {}
    for path, root in files:
        if root is not None and path not in failed:
            emptied.setdefault(root, set()).add(Path(path).parent)
    for root, folders in emptied.items():
        remove_empty_folders(folders, root)
    return failed


def failure_notice(failed: Sequence[str]) -> str:
    """What to tell the user about files Windows couldn't move to the Recycle Bin."""
    if len(failed) == 1:
        return f'Couldn\'t move "{Path(failed[0]).name}" to the Recycle Bin. Close it in other programs and try again.'
    names = ", ".join(Path(path).name for path in failed[:3]) + (", ..." if len(failed) > 3 else "")
    return f"Couldn't move {len(failed)} files to the Recycle Bin ({names}). Close them in other programs and try again."
