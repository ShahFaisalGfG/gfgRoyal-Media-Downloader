# helpers.py - small path utilities

import os
import sys


def resource_path(relative_path: str) -> str:
    """Return the absolute path to a bundled resource, for both source and PyInstaller builds."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(os.path.dirname(utils_dir))  # project root
    return os.path.normpath(os.path.join(base, relative_path))
