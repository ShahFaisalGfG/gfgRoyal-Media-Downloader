"""Collect QtNetwork without its plugins or an OpenSSL build.

The app uses QtNetwork only for its local single-instance pipe (QLocalServer and QLocalSocket),
so the TLS, network-information and network-access plugins are left out, along with any libssl or
libcrypto that PyInstaller's own hook would bundle for Qt's TLS backend. The update check, tool
installs, and thumbnails use Python's own urllib and ssl; yt-dlp makes its own connections.
"""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, _plugins, datas = add_qt6_dependencies(__file__)
binaries = []
