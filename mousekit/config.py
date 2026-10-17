"""Configuration: one JSON profile per mouse, keyed by "vvvv:pppp".

An action is a dict with a "type":
  default    the button's own click (only meaningful as a click action)
  disabled   swallow the press
  button     act as another mouse button          {"button": "BTN_MIDDLE"}
  shortcut   invoke a KDE global shortcut         {"component": "kwin", "name": "Overview"}
  keys       send a key combination               {"combo": "Ctrl+Alt+T"}
  command    run a shell command                  {"command": "..."}
  precision  slow the pointer while held          (click action only)

A button config has "click" (an action), "swipe" ({left,right,up,down} ->
action) and "wheel" ({up,down} -> action). A button with any swipe or wheel
action is held back on press and only clicks on release if no swipe or
wheel turn consumed the hold.
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mousekit"
CONFIG_PATH = CONFIG_DIR / "config.json"
SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}") / "mousekit.sock"

# Primary buttons always pass through untouched: remapping them can leave
# the user without a way to click.
LOCKED_BUTTONS = ("BTN_LEFT", "BTN_RIGHT")
SWIPE_DIRECTIONS = ("left", "right", "up", "down")
WHEEL_DIRECTIONS = ("up", "down")

DEFAULT_GESTURE = {"threshold": 50, "hold_ms": 160}
DEFAULT_PRECISION = 0.35
DEFAULT_ACTION = {"type": "default"}


def default_config():
    return {"version": 1, "devices": {}}


def new_profile(name):
    return {
        "name": name,
        "label": "",
        "enabled": False,
        "gesture": dict(DEFAULT_GESTURE),
        "precision": DEFAULT_PRECISION,
        "buttons": {},
    }


def normalize_profile(profile):
    profile.setdefault("name", "")
    profile.setdefault("label", "")
    profile.setdefault("enabled", False)
    gesture = profile.setdefault("gesture", {})
    for key, value in DEFAULT_GESTURE.items():
        gesture.setdefault(key, value)
    profile.setdefault("precision", DEFAULT_PRECISION)
    profile.setdefault("buttons", {})
    return profile


def load(path=CONFIG_PATH):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default_config()
    if not isinstance(data, dict):
        return default_config()
    data.setdefault("version", 1)
    devices = data.setdefault("devices", {})
    for profile in devices.values():
        normalize_profile(profile)
    return data


def save(config, path=CONFIG_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def button_config(profile, button):
    """The config for one button, with absent parts filled in."""
    raw = profile.get("buttons", {}).get(button, {})
    return {
        "click": raw.get("click") or DEFAULT_ACTION,
        "swipe": {d: a for d, a in raw.get("swipe", {}).items() if a and d in SWIPE_DIRECTIONS},
        "wheel": {d: a for d, a in raw.get("wheel", {}).items() if a and d in WHEEL_DIRECTIONS},
    }


def is_held(button_cfg):
    """Whether presses of this button are held back for swipe/wheel detection."""
    return bool(button_cfg["swipe"] or button_cfg["wheel"])
