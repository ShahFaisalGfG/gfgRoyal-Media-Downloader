# autostart.py - "Start with Windows" through the current user's Run key
#
# The app needs no administrator rights, so a per-user Run entry is enough (gfgShield, which runs
# elevated, needs a scheduled task instead). The entry starts the app in the tray with --background.
# Task Manager's Startup tab can disable the entry without deleting it; is_enabled() honors that.

from __future__ import annotations

import sys

from gfgmd.config.defaults import AppInfo

if sys.platform == "win32":
    import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = AppInfo.APP_NAME
BACKGROUND_FLAG = "--background"


def available() -> bool:
    """True for a frozen build on Windows (a source checkout has no stable exe to start)."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _command() -> str:
    return f'"{sys.executable}" {BACKGROUND_FLAG}'


def is_enabled() -> bool:
    """True when the Run entry exists and Task Manager hasn't disabled it."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as key:
            state, _ = winreg.QueryValueEx(key, VALUE_NAME)
        # The first byte is 2 (or 6) when enabled and 3 (or 7) when disabled in Task Manager.
        return not (isinstance(state, bytes) and state and state[0] & 1)
    except OSError:
        return True


def enable() -> tuple[bool, str]:
    """Add the Run entry; returns (ok, message for the user)."""
    if not available():
        return False, "Start with Windows works in the installed app."
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)  # clear a "disabled" left by Task Manager
        except OSError:
            pass
        return True, ""
    except OSError as error:
        return False, f"Couldn't turn on Start with Windows: {error}"


def disable() -> tuple[bool, str]:
    """Remove the Run entry."""
    if sys.platform != "win32":
        return True, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError as error:
        return False, f"Couldn't turn off Start with Windows: {error}"
    return True, ""
