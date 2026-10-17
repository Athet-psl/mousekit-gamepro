"""Mouse illustrations for the settings app, and a preview of the onboard lighting.

Each Art draws a top view into its own box and names the points callouts
attach to. The GM500W uses GamePro's product render with its light strips
traced so the real effect can be drawn over them; anything else gets a
generic symmetric mouse.
"""

import colorsys
import math
import random
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from . import effects, models
from .vendor import SINGLE_COLOUR_MODES

ASSETS = Path(__file__).resolve().parent / "assets"

LED_MODES = [
    "DPI colour breathing", "Colour-cycle breathing", "Static colour", "Flow", "Single-colour flow",
    "Comet", "Neon", "Ambilight", "Twinkle", "Star trail", "Ripple", "Colour dance",
    "Reactive", "Off",
]  # firmware modes 0-13; the vendor app's list stops at 13
# The vendor app doesn't tell us the DPI colours; this is the usual Instant default order.
DPI_COLOURS = [(255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 0), (0, 255, 255), (255, 0, 255)]


class Lighting:
    """What the mouse's LEDs are doing, and a colour for any point of a strip at a given time."""

    def __init__(self):
        self.mode = None        # None: unknown (no vendor channel)
        self.speed = 3
        self.colour = None      # last colour Mousekit set, for single-colour modes
        self.dpi_stage = 0
        self.flash_until = 0.0  # button-response flash
        self.effect_light = None  # a Mousekit effect setting, when one is streamed instead
        self.clicks = []          # click times, for the click-flash effect

    def known(self):
        return self.mode is not None or self.effect_light is not None

    def label(self):
        if self.effect_light:
            return f"{effects.EFFECTS.get(self.effect_light.get('effect'), 'Effect')} (Mousekit)"
        if self.mode is None:
            return "Unknown"
        return LED_MODES[self.mode] if self.mode < len(LED_MODES) else f"Mode {self.mode}"

    def animated(self):
        return self.effect_light is not None or self.mode not in (None, 2, 13)

    def uniform(self):
        """Whether every point of the strips has the same colour at a given moment."""
        if self.effect_light:
            return True  # Mousekit effects colour the whole mouse at once
        return self.mode in (0, 1, 2, 7, 8, 12)

    def colour_at(self, pos, now):
        """QColor (alpha = intensity) for strip position pos in 0..1, or None when dark."""
        if self.effect_light:
            del self.clicks[:-8]
            r, g, b = effects.colour(self.effect_light, now, self.clicks)
            level = max(r, g, b)
            if level < 3:
                return None
            # Full-strength hue with the intensity as alpha reads like a dimmer LED.
            return QColor(int(r * 255 / level), int(g * 255 / level), int(b * 255 / level), int(level))
        mode, rate = self.mode, 0.08 + 0.06 * self.speed
        base = QColor(*(self.colour or (235, 240, 255)))

        def hue(h, alpha=255):
            r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
            return QColor(int(r * 255), int(g * 255), int(b * 255), alpha)

        def breathe(period=3.0):
            return 0.2 + 0.8 * (0.5 + 0.5 * math.sin(2 * math.pi * now * rate * 6 / period))

        if mode is None or mode == 13:
            return None
        if mode == 2:
            return base
        if mode == 0:
            r, g, b = DPI_COLOURS[self.dpi_stage % len(DPI_COLOURS)]
            return QColor(r, g, b, int(255 * breathe()))
        if mode == 1:
            return hue(now * rate * 0.5, int(255 * breathe()))
        if mode in (3, 6):
            return hue(pos * (0.6 if mode == 3 else 1.0) - now * rate)
        if mode == 4:
            head = (now * rate * 2) % 1.4 - 0.2
            k = max(0.0, 1 - abs(pos - head) * 4)
            return QColor(base.red(), base.green(), base.blue(), int(40 + 215 * k))
        if mode == 5:
            head = (now * rate * 2.5) % 1.3
            k = max(0.0, 1 - (head - pos) * 3) if pos <= head else 0.0
            return hue(now * rate * 0.3, int(255 * k)) if k > 0 else None
        if mode == 7:
            return hue(now * rate * 0.35)
        if mode == 8:
            slot = int(now * (2 + self.speed))
            on = random.Random(slot).random() > 0.35
            return hue(random.Random(slot * 7).random()) if on else None
        if mode == 9:
            a = (now * rate * 2) % 1.0
            k = max(0.0, 1 - min(abs(pos - a), abs(pos - (a + 0.5) % 1.0)) * 6)
            return hue(now * rate * 0.2, int(255 * k)) if k > 0 else None
        if mode == 10:
            k = 0.5 + 0.5 * math.sin(2 * math.pi * (abs(pos - 0.5) * 2 - now * rate * 2))
            return hue(now * rate * 0.2, int(60 + 195 * k))
        if mode == 11:
            return hue(pos * 0.5 + 0.25 * math.sin(now * rate * 6))
        if mode == 12:
            return QColor(255, 255, 255, 230) if now < self.flash_until else QColor(255, 255, 255, 25)
        return hue(now * rate)


def _glow(p, path_points, colour_for, width, uniform=False):
    """Draw a lit strip: soft halo passes, then a bright core.

    A uniform colour is stroked as one path; a colour that varies along the
    strip is drawn segment by segment with flat caps so the halos don't bead.
    """
    passes = ((width * 2.4, 0.14), (width * 1.5, 0.3), (width, 1.0))
    if uniform:
        colour = colour_for(0.5)
        if colour is None:
            return
        path = QPainterPath(path_points[0][0])
        for point, _ in path_points[1:]:
            path.lineTo(point)
        segments = [(path, colour)]
    else:
        segments = [((a, b), colour_for((pa + pb) / 2)) for (a, pa), (b, pb) in zip(path_points, path_points[1:])]
    p.setBrush(Qt.BrushStyle.NoBrush)
    for halo, alpha_scale in passes:
        for shape, colour in segments:
            if colour is None:
                continue
            c = QColor(colour)
            if halo == width:  # whiten the core a little, like a real LED
                c = QColor(min(255, c.red() + 60), min(255, c.green() + 60), min(255, c.blue() + 60), c.alpha())
            c.setAlpha(int(c.alpha() * alpha_scale))
            pen = QPen(c, halo)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap if uniform else Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            if uniform:
                p.drawPath(shape)
            else:
                p.drawLine(*shape)


def _sample(path, start, end, steps=28):
    """Points along a path with their global strip position (start..end)."""
    return [(path.pointAtPercent(i / steps), start + (end - start) * i / steps) for i in range(steps + 1)]


class GenericArt:
    size = (300, 470)
    dots = {
        "BTN_MIDDLE": (150, 100),
        "BTN_TASK": (150, 163),
        "DPI": (150, 166),
        "BTN_EXTRA": (22, 220),
        "BTN_SIDE": (22, 276),
        "BTN_FORWARD": (278, 220),
        "BTN_BACK": (278, 276),
        "LIGHT": (150, 335),
    }

    @staticmethod
    def _body():
        path = QPainterPath(QPointF(150, 8))
        path.cubicTo(QPointF(228, 8), QPointF(268, 60), QPointF(272, 150))
        path.cubicTo(QPointF(276, 250), QPointF(292, 330), QPointF(272, 392))
        path.cubicTo(QPointF(252, 448), QPointF(200, 460), QPointF(150, 460))
        path.cubicTo(QPointF(100, 460), QPointF(48, 448), QPointF(28, 392))
        path.cubicTo(QPointF(8, 330), QPointF(24, 250), QPointF(28, 150))
        path.cubicTo(QPointF(32, 60), QPointF(72, 8), QPointF(150, 8))
        return path

    def paint(self, p, theme, buttons, lighting=None, now=0.0):
        body = self._body()
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(1, 9):
            p.setBrush(QColor(0, 0, 0, 16 if theme.dark else 9))
            p.drawPath(body.translated(k * 0.6, k * 1.6))
        outline = QPen(QColor("#a3a7ae"), 1.2)

        def side_button(x, y):
            grad = QLinearGradient(QPointF(x, 0), QPointF(x + 16, 0))
            grad.setColorAt(0, QColor("#c9ccd2"))
            grad.setColorAt(1, QColor("#eceef1"))
            p.setPen(outline)
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(x, y, 16, 50), 8, 8)

        for name, x, y in (("BTN_EXTRA", 13, 195), ("BTN_SIDE", 13, 251), ("BTN_FORWARD", 271, 195), ("BTN_BACK", 271, 251)):
            if name in buttons:
                side_button(x, y)
        _shell(p, body, outline, 20, 290)
        seam = QPen(QColor("#9ea2a9"), 1.3)
        p.setPen(seam)
        p.drawLine(QPointF(150, 9), QPointF(150, 52))
        p.drawLine(QPointF(150, 148), QPointF(150, 178))
        split = QPainterPath(QPointF(30, 196))
        split.cubicTo(QPointF(90, 174), QPointF(210, 174), QPointF(270, 196))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(split)
        _wheel(p, QRectF(128, 52, 44, 96), QRectF(136, 60, 28, 80))
        if "DPI" in buttons:
            p.setPen(outline)
            p.setBrush(QColor("#d9dbdf"))
            p.drawRoundedRect(QRectF(141, 153, 18, 12), 4, 4)
            p.drawRoundedRect(QRectF(141, 167, 18, 12), 4, 4)
        elif "BTN_TASK" in buttons:
            p.setPen(outline)
            p.setBrush(QColor("#d9dbdf"))
            p.drawRoundedRect(QRectF(141, 155, 18, 17), 5, 5)
        ring = QPainterPath()
        ring.addEllipse(QPointF(150, 350), 15, 15)
        if lighting is not None and lighting.known():
            _glow(p, _sample(ring, 0, 1, 24), lambda pos: lighting.colour_at(pos, now), 2.4, lighting.uniform())
        else:
            accent = QColor(theme.accent)
            accent.setAlpha(210)
            p.setPen(QPen(accent, 2.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(ring)


def _shell(p, body, outline, left, right):
    shell = QLinearGradient(QPointF(left, 0), QPointF(right, 0))
    shell.setColorAt(0, QColor("#e4e6e9"))
    shell.setColorAt(0.42, QColor("#f8f8fa"))
    shell.setColorAt(1, QColor("#c2c5cb"))
    p.setPen(outline)
    p.setBrush(shell)
    p.drawPath(body)
    rect = body.boundingRect()
    p.setPen(Qt.PenStyle.NoPen)
    shine = QRadialGradient(QPointF(rect.left() + rect.width() * 0.38, rect.top() + rect.height() * 0.24),
                            rect.width() * 0.6)
    shine.setColorAt(0, QColor(255, 255, 255, 150))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(shine)
    p.drawPath(body)
    rear = QLinearGradient(QPointF(0, rect.top() + rect.height() * 0.65), QPointF(0, rect.bottom()))
    rear.setColorAt(0, QColor(0, 0, 0, 0))
    rear.setColorAt(1, QColor(0, 0, 0, 38))
    p.setBrush(rear)
    p.drawPath(body)


def _wheel(p, well, wheel):
    grad = QLinearGradient(QPointF(well.left(), 0), QPointF(well.right(), 0))
    grad.setColorAt(0, QColor("#a9adb4"))
    grad.setColorAt(0.5, QColor("#c6c9ce"))
    grad.setColorAt(1, QColor("#a9adb4"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(well, well.width() / 2.6, well.width() / 2.6)
    tread = QLinearGradient(QPointF(wheel.left(), 0), QPointF(wheel.right(), 0))
    tread.setColorAt(0, QColor("#24262b"))
    tread.setColorAt(0.5, QColor("#4c5059"))
    tread.setColorAt(1, QColor("#24262b"))
    p.setBrush(tread)
    p.drawRoundedRect(wheel, 12, 12)
    p.setPen(QPen(QColor(120, 125, 136, 150), 1))
    y = wheel.top() + 6
    while y < wheel.bottom() - 4:
        p.drawLine(QPointF(wheel.left() + 4, y), QPointF(wheel.right() - 4, y))
        y += 6


class ImageArt:
    """A product render with the lit strips traced over it (coordinates in image pixels)."""

    def __init__(self, image, dots, strips, core=7):
        self.image = QImage(str(image))
        self.size = (self.image.width(), self.image.height())
        self.dots = dots
        self.core = core
        self.strips = []
        for points, start, end in strips:
            path = QPainterPath(QPointF(*points[0]))
            for pt in points[1:]:
                path.lineTo(QPointF(*pt))
            self.strips.append((path, start, end))

    def paint(self, p, theme, buttons, lighting=None, now=0.0):
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, *self.size), self.image)
        if lighting is not None and lighting.known():
            for path, start, end in self.strips:
                _glow(p, _sample(path, start, end, 36), lambda pos: lighting.colour_at(pos, now), self.core,
                      lighting.uniform())


def _shift(points, dx=-196, dy=-172):
    """Render pixel coordinates -> the cropped asset's (see tools/prepare_gm500w_render.py)."""
    return [(x + dx, y + dy) for x, y in points]


def gm500w_art():
    # Strip centre lines traced from the saturated pixels of GamePro's render.
    strips = [
        (_shift([(232, 765), (241, 770), (264, 790), (289, 810), (314, 830), (339, 850), (365, 870),
                 (397, 890), (418, 900), (449, 910), (478, 915)]), 0.00, 0.28),
        (_shift([(470, 606), (482, 618), (495, 632), (495, 912)]), 0.30, 0.50),
        (_shift([(540, 606), (528, 618), (514.5, 632), (514.5, 912)]), 0.50, 0.70),
        (_shift([(699, 605), (698.5, 630), (700, 660), (699.5, 700), (698, 720), (695, 740), (690.5, 760),
                 (683, 780), (673.5, 800), (661.5, 820), (646.5, 840), (628.5, 860), (606.5, 880),
                 (590.5, 890), (570.5, 900), (545, 910), (522, 915)]), 0.72, 1.00),
    ]
    dots = dict(zip(
        ("BTN_MIDDLE", "DPI", "FIRE", "BTN_EXTRA", "BTN_SIDE", "LIGHT", "DPI_UP", "DPI_DOWN", "FORWARD_KEY"),
        _shift([(507, 345), (507, 510), (327, 318), (328, 455), (335, 580), (514, 780),
                (507, 472), (507, 545), (328, 455)]),
    ))
    return ImageArt(ASSETS / "gm500w.png", dots, strips)


def art_for(key):
    model = models.identify(key)
    return gm500w_art() if model and model.get("art") == "gm500w" else GenericArt()
