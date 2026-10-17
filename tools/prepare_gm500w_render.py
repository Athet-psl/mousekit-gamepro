#!/usr/bin/python3
"""Turn GamePro's GM500W product render into the settings app's art.

Drops the cable above the shell, greys out the baked-in rainbow strips (the
app lights them itself with the mouse's real effect) and crops to the mouse.
Input: mousekit/assets/gm500w-render.png (transparent 1000x1000 PNG).
Output: mousekit/assets/gm500w.png; prints the crop offset used in drawing.py.
"""

import sys
from pathlib import Path

from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "mousekit" / "assets"
CABLE_BOTTOM = 176  # rows above this are only the cable


def main():
    QApplication(sys.argv[:1] + ["-platform", "offscreen"])
    src = QImage(str(ASSETS / "gm500w-render.png")).convertToFormat(QImage.Format.Format_ARGB32)
    out = QImage(src)
    left, top, right, bottom = src.width(), src.height(), 0, 0
    for y in range(src.height()):
        for x in range(src.width()):
            c = src.pixelColor(x, y)
            if y < CABLE_BOTTOM:
                out.setPixelColor(x, y, QColor(0, 0, 0, 0))
                continue
            if c.alpha() and c.hsvSaturationF() > 0.12 and c.valueF() > 0.25:
                g = int(196 + 22 * c.valueF())  # unlit diffuser grey, keeping some shading
                out.setPixelColor(x, y, QColor(g, g + 1, g + 3, c.alpha()))
            if c.alpha() > 10:
                left, top, right, bottom = min(left, x), min(top, y), max(right, x), max(bottom, y)
    left, top, right, bottom = left - 4, top - 4, right + 5, bottom + 5
    out.copy(left, top, right - left, bottom - top).save(str(ASSETS / "gm500w.png"))
    print(f"crop offset ({left}, {top}), size {right - left}x{bottom - top}")


if __name__ == "__main__":
    main()
