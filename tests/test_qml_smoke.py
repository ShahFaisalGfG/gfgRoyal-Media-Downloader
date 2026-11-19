import os

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from gfgmd.utils.helpers import resource_path


def test_all_qml_compiles(qapp):
    """Every component, page, and window compiles, which resolves the qmldir and all imports."""
    qml_dir = resource_path("gfgmd/qml")
    engine = QQmlEngine()
    engine.addImportPath(qml_dir)
    errors: list[str] = []
    found = 0
    for folder, _dirs, names in os.walk(qml_dir):
        for name in names:
            if not name.endswith(".qml"):
                continue
            found += 1
            component = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(folder, name)))
            if component.isError():
                errors.extend(error.toString() for error in component.errors())
    assert found > 0, f"no QML files under {qml_dir}"
    assert not errors, "\n".join(errors)
