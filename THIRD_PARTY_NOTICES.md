# Third-Party Notices

gfgRoyal Media Downloader is free and open-source software, released under the [MIT License](LICENSE).
The installers and the portable app bundle the open-source components below. Each keeps its own
licence, and the complete source for every one is available from the project linked.

The installers put this file in the `docs` folder of the install folder, the portable `.7z` next to
`gfgRoyal-Media-Downloader.exe`, and the portable exe carries it inside itself. The app itself is
pure Python and `ctypes`: it ships no native module of its own.

| Component | Licence | Used for |
|---|---|---|
| [Qt 6](https://www.qt.io/) and [Qt for Python (PySide6, shiboken6)](https://wiki.qt.io/Qt_for_Python) | LGPL-3.0-only | The user interface |
| [FFmpeg](https://ffmpeg.org/) libraries in Qt Multimedia (`avcodec`, `avformat`, `avutil`, `swresample`, `swscale`) | LGPL-2.1-or-later (Qt's build has no GPL parts) | The built-in video and music players |
| [Python](https://www.python.org/) 3.12 | PSF License 2.0, which also covers the libraries in Python's Windows build: bzip2, libffi, OpenSSL 3.0, SQLite, xz, zlib, expat, and mpdecimal | The app runtime, the library database, and HTTPS |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) bootloader | GPL-2.0-or-later with the bootloader exception, which allows distributing it with any program | Starting the bundled app, `gfgmd.exe`, and the companion's host |
| Microsoft Visual C++ runtime and Universal C Runtime | Microsoft's redistribution terms (see below) | Running the bundled runtime |

## Programs downloaded separately, not bundled

The app downloads these programs from their official releases (GitHub, and Codeberg for gallery-dl)
when you first use it (or uses copies you installed yourself). They are separate programs under their own licences; the app runs
them and never includes or modifies them.

| Program | Licence | Source |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | The Unlicense (public domain) | <https://github.com/yt-dlp/yt-dlp/releases> |
| [FFmpeg](https://ffmpeg.org/) and ffprobe, yt-dlp's builds | GPL-3.0-or-later (these builds include GPL components) | <https://github.com/yt-dlp/FFmpeg-Builds/releases>, source at <https://ffmpeg.org/download.html> |
| [Deno](https://deno.com/) | MIT | <https://github.com/denoland/deno/releases> |
| [gallery-dl](https://github.com/mikf/gallery-dl) | GPL-2.0-only | <https://codeberg.org/mikf/gallery-dl/releases> |
| [spotDL](https://github.com/spotDL/spotify-downloader) | MIT | <https://github.com/spotDL/spotify-downloader/releases> |

## Qt and PySide6 (LGPL-3.0)

Qt and PySide6 are used as separate, replaceable libraries: the installed app keeps them as
individual DLL and `.pyd` files in its `_internal` folder, so they can be swapped for other builds of
the same version. Their source is available from <https://download.qt.io/> and <https://code.qt.io/>.
The same holds for the FFmpeg DLLs Qt Multimedia uses; FFmpeg's source is at
<https://ffmpeg.org/download.html>, and Qt documents its build at
<https://doc.qt.io/qt-6/qtmultimedia-building-ffmpeg-windows.html>.

The Qt DLLs include third-party code under its own permissive licences, for example PCRE2 and zlib in
`Qt6Core.dll`, HarfBuzz and libpng in `Qt6Gui.dll`, and libjpeg-turbo, libtiff, and libwebp in the
image format plugins. Qt lists every one with its licence at
<https://doc.qt.io/qt-6/licenses-used-in-qt.html>.

## Microsoft runtime libraries

`VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`, `MSVCP140.dll`, `MSVCP140_1.dll`, and `MSVCP140_2.dll` (the
Visual C++ runtime, shipped by Python and PySide6), and `ucrtbase.dll` with the `api-ms-win-*.dll`
files (the Universal C Runtime), are Microsoft's redistributable files. They are distributed under the
Visual Studio redistribution terms, which allow shipping them with an application; Windows 10 and
later include the Universal C Runtime. Python's licence above describes the conditions for the copies
that come with Python.

## Companion browser extension

The companion extension (in `companion/`, released under the MIT License) bundles WXT's runtime
helpers (MIT); its own `THIRD_PARTY_NOTICES.md` lists them.
