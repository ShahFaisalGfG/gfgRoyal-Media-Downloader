"""The engine, the command-line tool, and the native host never import Qt, so they run without PySide6."""

import subprocess
import sys

MODULES = [
    "gfgmd.cli",
    "gfgmd.config.defaults",
    "gfgmd.utils.launch",
    "gfgmd.utils.paths",
    "gfgmd.utils.format",
    "gfgmd.utils.agent_skills",
    "gfgmd.services.companion",
    "gfgmd.host_entry",
    "gfgmd.core.analyze",
    "gfgmd.core.archive",
    "gfgmd.core.auth",
    "gfgmd.core.benchmark",
    "gfgmd.core.captions",
    "gfgmd.core.command",
    "gfgmd.core.errors",
    "gfgmd.core.jobs",
    "gfgmd.core.locks",
    "gfgmd.core.lyrics",
    "gfgmd.core.naming",
    "gfgmd.core.options",
    "gfgmd.core.platform",
    "gfgmd.core.progress",
    "gfgmd.core.quick_info",
    "gfgmd.core.retry",
    "gfgmd.core.runner",
    "gfgmd.core.schedule",
    "gfgmd.core.secret_store",
    "gfgmd.core.sites",
    "gfgmd.core.sources",
    "gfgmd.core.store",
    "gfgmd.core.subscriptions",
    "gfgmd.core.tool_install",
    "gfgmd.core.tools",
    "gfgmd.core.web",
]


def test_core_has_no_qt_imports() -> None:
    """Import each module in a fresh interpreter and check no PySide6 module was loaded."""
    code = (
        "import importlib, sys\n"
        f"for name in {MODULES!r}:\n"
        "    importlib.import_module(name)\n"
        "print(sorted(m for m in sys.modules if m.startswith(('PySide6', 'shiboken6'))))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
