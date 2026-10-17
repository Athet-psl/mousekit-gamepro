"""Mousekit's own lighting effects, streamed to the mouse by the daemon.

The mouse sits in static-colour mode, which shows the colour slot of the
current DPI stage, and the daemon rewrites those slots ~30 times a second.
That gives smooth fades the firmware's own effects can't do, but only for
the whole mouse at once: the protocol has no per-zone colours.
"""

import colorsys
import math

FPS = 30
SLOTS = 6  # one colour per DPI stage; static mode shows the current stage's

EFFECTS = {
    "breathe": "Smooth breathing",
    "rainbow": "Smooth rainbow",
    "click": "Click flash",
}
NEEDS_COLOUR = {"breathe", "click"}
CLICK_FADE = 0.45  # seconds a click flash takes to fade


def _hsv(h, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, v)
    return (r * 255, g * 255, b * 255)


def _scale(rgb, k):
    return tuple(c * k for c in rgb)


def colour(light, t, clicks=()):
    """(r, g, b) 0-255 of effect light["effect"] at time t (seconds)."""
    effect = light.get("effect")
    rate = 0.35 + 0.3 * light.get("speed", 2)            # speed 0-5
    level = max(1, min(7, light.get("bright", 7))) / 7   # brightness 1-7
    base = tuple(light.get("color") or (255, 255, 255))
    if effect == "breathe":
        k = 0.08 + 0.92 * (0.5 - 0.5 * math.cos(2 * math.pi * t * rate * 0.35))
        rgb = _scale(base, k)
    elif effect == "rainbow":
        rgb = _hsv(t * rate * 0.08)
    elif effect == "click":
        # Glows at the background level in the same colour; a click flashes to full and fades back.
        glow = max(0, min(6, light.get("glow", 3))) / 10
        flash = 0.0
        for when in clicks:
            age = t - when
            if 0 <= age < CLICK_FADE:
                flash = max(flash, 1 - age / CLICK_FADE)
        rgb = _scale(base, glow + (1 - glow) * flash)
    else:
        rgb = base
    return _scale(rgb, level)


def to_device(rgb):
    """Perceptual correction before the mouse's 16 levels per channel."""
    return tuple(255 * (max(0.0, min(255.0, c)) / 255) ** 1.8 for c in rgb)
