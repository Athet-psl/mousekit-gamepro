"""Mouse discovery through sysfs, so listing devices needs no device access."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from evdev import ecodes as e

VIRTUAL_PREFIX = "Mousekit"
INPUT_PROP_POINTING_STICK = 0x05

BUTTON_NAMES = {
    e.BTN_LEFT: "BTN_LEFT",
    e.BTN_RIGHT: "BTN_RIGHT",
    e.BTN_MIDDLE: "BTN_MIDDLE",
    e.BTN_SIDE: "BTN_SIDE",
    e.BTN_EXTRA: "BTN_EXTRA",
    e.BTN_FORWARD: "BTN_FORWARD",
    e.BTN_BACK: "BTN_BACK",
    e.BTN_TASK: "BTN_TASK",
}
BUTTON_CODES = {name: code for code, name in BUTTON_NAMES.items()}


@dataclass
class MouseInfo:
    key: str            # "vvvv:pppp", the config key
    name: str
    node: str           # /dev/input/eventN
    buttons: list = field(default_factory=list)  # BUTTON_NAMES values
    accessible: bool = False


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _bits(path):
    """Set bits of a sysfs capability bitmap (space-separated hex words, MSB word first)."""
    words = _read(path).split()
    bits = set()
    for index, word in enumerate(reversed(words)):
        value = int(word, 16)
        base = index * 64
        while value:
            low = value & -value
            bits.add(base + low.bit_length() - 1)
            value ^= low
    return bits


def key_interfaces(key):
    """Event nodes of mouse "vvvv:pppp"'s keyboard-like interfaces (media keys programmed in the mouse)."""
    nodes = []
    for event in sorted(Path("/sys/class/input").glob("event*"), key=lambda p: int(p.name[5:])):
        dev = event / "device"
        if "/devices/virtual/" in os.path.realpath(dev):
            continue
        ids = f"{_read(dev / 'id/vendor')}:{_read(dev / 'id/product')}"
        keys = _bits(dev / "capabilities/key")
        if ids == key and e.KEY_PLAYPAUSE in keys and e.BTN_LEFT not in keys:
            nodes.append(f"/dev/input/{event.name}")
    return nodes


def scan():
    """All physical mice currently connected, in event-node order."""
    mice = []
    for event in sorted(Path("/sys/class/input").glob("event*"), key=lambda p: int(p.name[5:])):
        dev = event / "device"
        name = _read(dev / "name")
        if not name or name.startswith(VIRTUAL_PREFIX):
            continue
        # uinput devices (ours or other tools') live under /devices/virtual;
        # I2C pointers are the laptop's own touchpad companions.
        if "/devices/virtual/" in os.path.realpath(dev) or _read(dev / "id/bustype") == "0018":
            continue
        rel = _bits(dev / "capabilities/rel")
        keys = _bits(dev / "capabilities/key")
        if not ({e.REL_X, e.REL_Y} <= rel and e.BTN_LEFT in keys):
            continue
        # Touchpads, tablets and touchscreens report absolute axes; their
        # streams can't be re-injected faithfully, so they are never managed.
        if _bits(dev / "capabilities/abs") or INPUT_PROP_POINTING_STICK in _bits(dev / "properties"):
            continue
        vendor = int(_read(dev / "id/vendor") or "0", 16)
        product = int(_read(dev / "id/product") or "0", 16)
        node = f"/dev/input/{event.name}"
        mice.append(MouseInfo(
            key=f"{vendor:04x}:{product:04x}",
            name=name,
            node=node,
            buttons=[n for c, n in BUTTON_NAMES.items() if c in keys],
            accessible=os.access(node, os.R_OK),
        ))
    return mice
