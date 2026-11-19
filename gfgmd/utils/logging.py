# logging.py - log file management utilities

import os
import threading
from datetime import datetime
from typing import IO

from gfgmd.utils.console import safe_print
from gfgmd.utils.paths import data_dir
from gfgmd.utils.settings import load_settings

# A log that grows past this size moves to its backup (name + BACKUP_SUFFIX, replacing the older
# one) and starts over, so the logs never take more than about twice this much space each.
ROTATE_BYTES = 5 * 1024 * 1024
BACKUP_SUFFIX = ".1"


def get_logs_dir() -> str:
    """The logs directory (in the app's data folder, or the project when run from source)."""
    folder = data_dir()
    if folder:
        logs_dir = os.path.join(folder, "logs")
    else:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.join(os.path.dirname(os.path.dirname(utils_dir)), "logs")  # project root
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except OSError:
        pass  # the write that needs the folder fails next and reports it
    return logs_dir


def get_critical_log_file() -> str:
    """The path to the critical (errors) log file."""
    return os.path.join(get_logs_dir(), "gfgmd_critical.log")


def get_general_log_file() -> str:
    """The path to the full activity log file."""
    return os.path.join(get_logs_dir(), "gfgmd_full_activity.log")


def write_log(message: str, level: str = "general", force: bool = False) -> bool:
    """Write one log line as the logging preferences allow; True when it was written.

    level="critical" goes to the critical log whenever logging is on; level="general" goes to the
    activity log when the level is "Everything". force=True writes the critical log even with
    logging off, for failures that happen before the preferences can be trusted (startup).
    """
    if force:
        return _append(get_critical_log_file(), _line(message))
    critical_on, general_on = _enabled_logs()
    if level == "critical":
        return critical_on and _append(get_critical_log_file(), _line(message))
    return general_on and _append(get_general_log_file(), _line(message))


def clear_logs() -> bool:
    """Empty both logs and delete their backups. Returns True if all of it worked."""
    ok = True
    for log_file in (get_critical_log_file(), get_general_log_file()):
        try:
            if os.path.exists(log_file):
                open(log_file, "w", encoding="utf-8").close()
            if os.path.exists(log_file + BACKUP_SUFFIX):
                os.remove(log_file + BACKUP_SUFFIX)
        except OSError as error:
            safe_print(f"Could not clear {log_file}: {error}")
            ok = False
    return ok


_write_lock = threading.Lock()


def _enabled_logs() -> tuple[bool, bool]:
    """(critical log on, activity log on) as the logging preferences say; both off if unreadable."""
    try:
        advanced = load_settings().get("advanced", {})
    except Exception as error:  # logging runs inside error handlers, so it must never raise
        safe_print(f"Could not read the logging preferences: {error}")
        return False, False
    enabled = bool(advanced.get("enable_logs", False))
    return enabled, enabled and advanced.get("log_level", "critical") == "all"


def _line(message: str) -> str:
    """One timestamped log line."""
    return f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n"


def _open(path: str) -> IO[str]:
    """Open a log for appending; odd characters in file names are escaped, never an error."""
    return open(path, "a", encoding="utf-8", errors="backslashreplace")


def _append(path: str, text: str) -> bool:
    """Append text to the log at path, rotating the log first when it is full."""
    with _write_lock:
        try:
            _rotate_if_full(path)
            with _open(path) as handle:
                handle.write(text)
            return True
        except OSError as error:
            safe_print(f"Could not write to {path}: {error}")
            return False


def _rotate_if_full(path: str) -> None:
    """Move a log past ROTATE_BYTES to its backup so it starts over."""
    try:
        if os.path.getsize(path) < ROTATE_BYTES:
            return
        os.replace(path, path + BACKUP_SUFFIX)
    except FileNotFoundError:
        return
    except OSError as error:
        safe_print(f"Could not rotate {path}: {error}")
