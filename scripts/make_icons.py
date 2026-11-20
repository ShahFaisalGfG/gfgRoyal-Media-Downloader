"""Draw every gfgRoyal Media Downloader icon from code: the window, taskbar and About sizes, the
splash logo, the readme logo, and the .ico for the exe and the installers.

The app shares the gfgRoyal icon family: a rounded tile with a diagonal gradient and a bold white
symbol, no text, so the icon stays recognisable at 16 px. Each app has its own colours and symbol;
the downloader's gradient ends in the app's rose accent (Theme.accentFill), and its symbol is a
rounded play triangle with a round download badge on its corner.

Run from any folder:  python scripts/make_icons.py
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QImageWriter, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen)

# Resolved from this script's location (scripts/), so it runs from any working directory.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(_REPO_ROOT, "gfgmd", "assets", "icons")
os.makedirs(ICON_DIR, exist_ok=True)
TOP, BOTTOM = "#f43f5e", "#be123c"  # rose to the app's accent, so the icon matches its buttons
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


def _round_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_play(p: QPainter, cx: float, cy: float, height: float) -> None:
    """A white play triangle with rounded corners, centred by eye on (cx, cy).

    The corners come from a round-joined stroke around a smaller triangle, so they stay round at
    every size. A triangle's visual centre sits left of its box's centre, so it is drawn a little left.
    """
    corner = height * 0.12
    inner = height - 3.4 * corner
    width = inner * 0.92
    left = cx - width * 0.42
    path = QPainterPath()
    path.moveTo(left, cy - inner / 2)
    path.lineTo(left + width, cy)
    path.lineTo(left, cy + inner / 2)
    path.closeSubpath()
    white = QColor("white")
    p.setPen(_round_pen(white, 2 * corner))
    p.setBrush(white)
    p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)


def draw_symbol(p: QPainter, s: float) -> None:
    """A rounded play triangle with a white download badge on its lower right.

    The badge sits in a ring of the tile's darker colour, so it reads as a badge, not part of the
    triangle. Up to 24 px the badge is larger and its arrow bolder and shorter, so it stays readable.
    """
    small = s <= 24
    draw_play(p, s * 0.45, s * 0.45, s * (0.52 if small else 0.50))
    centre = QPointF(s * 0.70, s * 0.70)
    radius = s * (0.20 if small else 0.17)
    p.setBrush(QColor(BOTTOM))
    gap = s * (0.03 if small else 0.035)
    p.drawEllipse(centre, radius + gap, radius + gap)
    p.setBrush(QColor("white"))
    p.drawEllipse(centre, radius, radius)
    if s <= 20:
        # A few pixels wide, strokes blur together: a solid triangle pointing down reads as the arrow.
        head = QPainterPath()
        half = radius * 0.58
        head.moveTo(centre.x() - half, centre.y() - half * 0.55)
        head.lineTo(centre.x() + half, centre.y() - half * 0.55)
        head.lineTo(centre.x(), centre.y() + half * 0.75)
        head.closeSubpath()
        p.fillPath(head, QColor(BOTTOM))
        return
    # The arrow: a shaft and an open head, round-capped, in the tile's colour.
    p.setPen(_round_pen(QColor(BOTTOM), s * (0.075 if small else 0.045)))
    shaft_top = centre.y() - radius * (0.38 if small else 0.48)
    tip = centre.y() + radius * (0.42 if small else 0.45)
    head = radius * (0.40 if small else 0.42)
    p.drawLine(QPointF(centre.x(), shaft_top), QPointF(centre.x(), tip))
    p.drawPolyline([QPointF(centre.x() - head, tip - head * 0.95), QPointF(centre.x(), tip),
                    QPointF(centre.x() + head, tip - head * 0.95)])
    p.setPen(Qt.PenStyle.NoPen)


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
