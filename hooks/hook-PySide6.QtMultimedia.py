"""Collect QtMultimedia with only its FFmpeg backend.

The players run on Qt's FFmpeg backend, which app.py names in QT_MEDIA_BACKEND, so the Windows Media
Foundation backend (windowsmediaplugin.dll) is never loaded and is left out. The FFmpeg libraries the
backend uses (avcodec, avformat, avutil, swresample, swscale) come along as its dependencies.
"""

from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, _binaries, datas = add_qt6_dependencies(__file__)
binaries = [entry for entry in _binaries if Path(entry[0]).name.casefold() != "windowsmediaplugin.dll"]
