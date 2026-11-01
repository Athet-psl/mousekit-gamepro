"""Draws Mousekit's app icon: mousekit/assets/mousekit.png and data/mousekit.ico (for the Windows build).

    python tools/make_icon.py      (needs PyQt6; the .ico also needs Pillow)
"""

import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parent.parent


def draw(size):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)

    body = QPainterPath()
    body.addRoundedRect(QRectF(58, 14, 140, 228), 70, 70)
    shell = QLinearGradient(QPointF(58, 14), QPointF(198, 242))
    shell.setColorAt(0, QColor("#3a3d46"))
    shell.setColorAt(1, QColor("#16171b"))
    p.setPen(QPen(QColor("#0c0d10"), 4))
    p.setBrush(shell)
    p.drawPath(body)

    glow = QLinearGradient(QPointF(58, 0), QPointF(198, 0))
    for stop, colour in ((0, "#ff3b6b"), (0.35, "#ffb020"), (0.65, "#2bd9a0"), (1, "#3a7bff")):
        glow.setColorAt(stop, QColor(colour))
    p.setPen(QPen(glow, 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(70, 110, 116, 120), 200 * 16, 140 * 16)

    p.setPen(QPen(QColor("#0c0d10"), 4))
    p.drawLine(QPointF(128, 16), QPointF(128, 100))
    p.drawLine(QPointF(60, 100), QPointF(196, 100))
    wheel = QLinearGradient(QPointF(0, 40), QPointF(0, 84))
    wheel.setColorAt(0, QColor("#5ee3ff"))
    wheel.setColorAt(1, QColor("#3a7bff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(wheel)
    p.drawRoundedRect(QRectF(118, 38, 20, 48), 10, 10)
    p.end()
    return image


def main():
    QGuiApplication(sys.argv)
    png = ROOT / "mousekit" / "assets" / "mousekit.png"
    draw(256).save(str(png))
    print(png)
    try:
        from PIL import Image
    except ImportError:
        print("Pillow isn't installed: skipped the .ico")
        return
    ico = ROOT / "data" / "mousekit.ico"
    Image.open(png).save(ico, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    print(ico)


if __name__ == "__main__":
    main()
