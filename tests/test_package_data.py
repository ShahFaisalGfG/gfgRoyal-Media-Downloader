"""A pip-installed copy carries every QML file the app loads, as the installers and portable builds do."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "gfgmd"


def test_package_data_covers_every_qml_file():
    """A QML file or qmldir left out of the package data stops a pip-installed app from loading its window."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["gfgmd"]
    covered = {path for pattern in patterns for path in PACKAGE.glob(pattern)}
    shipped = {path for path in (PACKAGE / "qml").rglob("*") if path.is_file() and "__pycache__" not in path.parts}
    missing = sorted(str(path.relative_to(PACKAGE)) for path in shipped - covered)
    assert not missing, f"not in [tool.setuptools.package-data]: {missing}"
