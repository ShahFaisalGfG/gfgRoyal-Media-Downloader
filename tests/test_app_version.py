# test_app_version.py - the version the app shows and the updater compares

import os
import tomllib

from gfgmd.config.defaults import AppInfo

_PYPROJECT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")


def test_app_version_matches_pyproject():
    """Releases are named from pyproject; a different AppInfo version would offer the installed release forever."""
    with open(_PYPROJECT, "rb") as fh:
        assert AppInfo.APP_VERSION == tomllib.load(fh)["project"]["version"]
