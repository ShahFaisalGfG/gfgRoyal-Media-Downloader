# recycle.py - move files to the Recycle Bin (never a permanent delete)

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from gfgmd.core.captions import companion_files

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
    return result == 0 and not operation.fAnyOperationsAborted


def recycle_media(paths: list[str]) -> bool:
    """Send media files, with the captions, lyrics, and covers saved beside them, to the Recycle Bin.

    True when Windows moved them, or when none of the files is there any more.
    """
    files = [str(entry) for path in paths if os.path.isfile(path)
             for entry in (Path(path), *companion_files(Path(path)))]
    return not files or to_recycle_bin(files)
