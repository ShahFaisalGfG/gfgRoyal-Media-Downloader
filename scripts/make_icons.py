"""Draw every gfgRoyal Media Downloader icon from code: the window, taskbar and About sizes, the
splash logo, the readme logo, and the .ico for the exe and the installers.

The app shares the gfgRoyal icon family: a rounded tile with a diagonal gradient and a bold white
symbol, no text, so the icon stays recognisable at 16 px. Each app has its own colours and symbol;
the downloader keeps the rose-to-orange of its portfolio card and draws a play triangle with a
download arrow below it.

Run from any folder:  python scripts/make_icons.py
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QImageWriter, QLinearGradient, QPainter, QPainterPath  # noqa: E402

# Resolved from this script's location (scripts/), so it runs from any working directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(_REPO_ROOT, "gfgmd", "assets", "icons")
os.makedirs(ICON_DIR, exist_ok=True)
TOP, BOTTOM = "#f43f5e", "#f97316"  # rose to orange
PNGS = {
    "Square44x44Logo.targetsize-16.png": 16,
    "Square44x44Logo.targetsize-20.png": 20,
    "Square44x44Logo.targetsize-24.png": 24,
    "Square44x44Logo.targetsize-32.png": 32,
    "Square44x44Logo.targetsize-48.png": 48,
    "Square44x44Logo.targetsize-256.png": 256,
    "Square71x71Logo.scale-100.png": 71,
    "Square150x150Logo.scale-100.png": 150,
    "Square310x310Logo.scale-100.png": 310,
    "StoreLogo.scale-150.png": 150,
    "gfgRoyal-Media-Downloader.png": 1024,
}
ICO_NAME = "gfgRoyal-Media-Downloader.ico"
# The companion browser extension's toolbar and store icons, drawn the same way.
COMPANION_DIR = os.path.join(_REPO_ROOT, "companion", "public", "icon")
COMPANION_SIZES = (16, 32, 48, 128)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def draw_tile(p: QPainter, size: float, top: str, bottom: str) -> None:
    """The shared shape: a rounded square with a diagonal gradient and a thin transparent margin."""
    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(1, QColor(bottom))
    inset = size * 0.04
    path = QPainterPath()
    path.addRoundedRect(QRectF(inset, inset, size - 2 * inset, size - 2 * inset), size * 0.22, size * 0.22)
    p.fillPath(path, grad)


def draw_symbol(p: QPainter, s: float) -> None:
    """A white play triangle with a download arrow and its tray line beneath it.

    Below 32 px only the play triangle and arrow are drawn, larger, so the symbol stays readable.
    """
    white = QColor("white")
    p.setPen(Qt.PenStyle.NoPen)
    small = s < 32
    # Play triangle, upper half.
    play = QPainterPath()
    left, top = s * (0.36 if small else 0.38), s * (0.20 if small else 0.18)
    height = s * (0.36 if small else 0.30)
    play.moveTo(left, top)
    play.lineTo(left + height * 0.9, top + height / 2)
    play.lineTo(left, top + height)
    play.closeSubpath()
    p.fillPath(play, white)
    # Download arrow: a shaft and a head pointing down.
    shaft_w = s * (0.11 if small else 0.08)
    shaft_top = top + height + s * 0.04
    head_top = s * (0.66 if small else 0.62)
    p.fillRect(QRectF(s / 2 - shaft_w / 2, shaft_top, shaft_w, head_top - shaft_top), white)
    head = QPainterPath()
    half = s * (0.17 if small else 0.14)
    head.moveTo(s / 2 - half, head_top)
    head.lineTo(s / 2 + half, head_top)
    head.lineTo(s / 2, head_top + half * 1.05)
    head.closeSubpath()
    p.fillPath(head, white)
    if not small:
        # The tray line the arrow lands on.
        p.fillRect(QRectF(s * 0.28, s * 0.80, s * 0.44, s * 0.055), white)


def render(size: int) -> QImage:
    """The icon at one exact size, drawn as vectors so small sizes stay sharp."""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_tile(p, size, TOP, BOTTOM)
    draw_symbol(p, size)
    p.end()
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    QImageWriter(buffer, QByteArray(b"png")).write(img)
    buffer.close()
    return bytes(data.data())


def write_ico(path: str, sizes: tuple[int, ...]) -> None:
    """A Windows .ico with one PNG-compressed image per size (supported since Windows Vista)."""
    images = [png_bytes(render(size)) for size in sizes]
    offset = 6 + 16 * len(sizes)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    for size, data in zip(sizes, images):
        dim = 0 if size >= 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(header + entries + b"".join(images))


def main() -> None:
    QGuiApplication(sys.argv[:1])
    for name, size in PNGS.items():
        render(size).save(os.path.join(ICON_DIR, name))  # PNG, from the file name
    write_ico(os.path.join(ICON_DIR, ICO_NAME), ICO_SIZES)
    os.makedirs(COMPANION_DIR, exist_ok=True)
    for size in COMPANION_SIZES:
        render(size).save(os.path.join(COMPANION_DIR, f"{size}.png"))
    print(f"Wrote {len(PNGS)} PNGs and {ICO_NAME} to {ICON_DIR}, and the companion's icons to {COMPANION_DIR}")


if __name__ == "__main__":
    main()
