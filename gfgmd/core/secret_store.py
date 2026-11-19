"""Encrypt sign-in data at rest: Windows DPAPI for the current user, file permissions elsewhere.

DPAPI ties the encryption to the signed-in Windows account, so a copied file (or a portable copy
moved to another PC) can't be read; the app then asks for a new sign-in. Without DPAPI (Linux
and macOS command-line use) the data is stored in a file only its owner can read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MAGIC_DPAPI = b"GFGD1"
_MAGIC_PLAIN = b"GFGP1"


class SecretError(Exception):
    """Stored sign-in data can't be read (another Windows account or PC, or a damaged file)."""


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), wintypes.LPVOID,
                                  wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _CryptProtectData.restype = wintypes.BOOL
    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPVOID, ctypes.POINTER(_Blob), wintypes.LPVOID,
                                    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _CryptUnprotectData.restype = wintypes.BOOL
    _LocalFree = _kernel32.LocalFree
    _LocalFree.argtypes = [wintypes.HLOCAL]
    _LocalFree.restype = wintypes.HLOCAL
    _UI_FORBIDDEN = 0x1

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _take(blob: _Blob) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))

    def protect(data: bytes, entropy: bytes) -> bytes:
        """Encrypt for the current Windows user."""
        source, _keep1 = _blob(data)
        extra, _keep2 = _blob(entropy)
        result = _Blob()
        if not _CryptProtectData(ctypes.byref(source), "gfgRoyal Media Downloader sign-in", ctypes.byref(extra),
                                 None, None, _UI_FORBIDDEN, ctypes.byref(result)):
            raise SecretError(f"Windows couldn't encrypt the sign-in (error {ctypes.get_last_error()})")
        return _MAGIC_DPAPI + _take(result)

    def unprotect(data: bytes, entropy: bytes) -> bytes:
        """Decrypt data protect() wrote for this Windows user."""
        if not data.startswith(_MAGIC_DPAPI):
            raise SecretError("The sign-in file isn't in a format this app wrote")
        source, _keep1 = _blob(data[len(_MAGIC_DPAPI):])
        extra, _keep2 = _blob(entropy)
        result = _Blob()
        if not _CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(extra), None, None, _UI_FORBIDDEN,
                                   ctypes.byref(result)):
            raise SecretError("The saved sign-in belongs to another Windows account or PC; sign in again")
        return _take(result)
else:
    def protect(data: bytes, entropy: bytes) -> bytes:
        """Without DPAPI the data is stored as is in an owner-only file (see write_secret)."""
        return _MAGIC_PLAIN + data

    def unprotect(data: bytes, entropy: bytes) -> bytes:
        """Read data protect() wrote."""
        if not data.startswith(_MAGIC_PLAIN):
            raise SecretError("The sign-in file isn't in a format this app wrote")
        return data[len(_MAGIC_PLAIN):]


def write_secret(path: Path, data: bytes, entropy: bytes) -> None:
    """Encrypt and write atomically, readable only by the current user where the OS supports it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = protect(data, entropy)
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def read_secret(path: Path, entropy: bytes) -> bytes:
    """Read and decrypt; raises SecretError when it can't be decrypted, FileNotFoundError when absent."""
    return unprotect(path.read_bytes(), entropy)


def wipe(path: Path) -> None:
    """Overwrite a plain-text file with zeros, then delete it (best effort on SSDs)."""
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(b"\0" * size)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    path.unlink(missing_ok=True)
