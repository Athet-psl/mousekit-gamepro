"""Per-mouse event processing: button remaps, hold-and-swipe, hold-and-wheel, precision.

Pure logic over an output (the mirror device) and an action runner, so it
can be tested without hardware. Swipe detection follows OpenLogi
(github.com/AprilNEA/OpenLogi, crates/openlogi-core/src/binding/swipe.rs):
the cursor keeps moving during a hold, and a swipe commits mid-motion, once
per hold, as soon as a reasonably straight direction passes the threshold
after the hold gate.
"""

import time

from evdev import ecodes as e

from .config import DEFAULT_GESTURE, DEFAULT_PRECISION, LOCKED_BUTTONS, button_config, is_held
from .devices import BUTTON_CODES, BUTTON_NAMES

SWIPE_DEADZONE = 40  # cross-axis travel allowed at the threshold: max(this, 35% of dominant)
VERTICAL_WHEEL = (e.REL_WHEEL, e.REL_WHEEL_HI_RES)


def detect_swipe(dx, dy, threshold):
    """Direction of the running travel once it commits, else None."""
    ax, ay = abs(dx), abs(dy)
    dominant = max(ax, ay)
    if dominant < threshold:
        return None
    cross_limit = max(SWIPE_DEADZONE, dominant * 35 // 100)
    if ax > ay:
        if ay > cross_limit:
            return None
        return "right" if dx > 0 else "left"
    if ax > cross_limit:
        return None
    return "down" if dy > 0 else "up"


class Hold:
    """A held-back press of a button that has swipe or wheel actions."""

    def __init__(self, code, since, cfg):
        self.code = code
        self.since = since
        self.cfg = cfg
        self.dx = self.dy = 0
        self.consumed = False


class Engine:
    def __init__(self, out, actions, notify=lambda event: None, key=""):
        self.out = out            # .write(type, code, value), .syn()
        self.actions = actions    # .tap(action), .press(action), .release(action)
        self.notify = notify
        self.key = key
        self.profile = {}
        self.hold = None
        self.pressed = {}         # code -> action applied at press, released on release
        self.precision = 0        # number of held precision buttons
        self.remainder = {e.REL_X: 0.0, e.REL_Y: 0.0}

    def set_profile(self, profile):
        self.profile = profile or {}

    def reset(self):
        """Release everything this engine is holding down (device lost or ungrabbed)."""
        for code, action in list(self.pressed.items()):
            self._release(code, action)
        self.pressed.clear()
        self.hold = None
        self.precision = 0
        self.out.syn()

    def handle(self, type_, code, value, now=None):
        now = time.monotonic() if now is None else now
        if type_ == e.EV_KEY and code in BUTTON_NAMES:
            self._button(code, value, now)
        elif type_ == e.EV_REL and code in (e.REL_X, e.REL_Y):
            self._motion(code, value, now)
        elif type_ == e.EV_REL and code in VERTICAL_WHEEL and self.hold and self.hold.cfg["wheel"]:
            self._wheel(code, value)
        else:
            self.out.write(type_, code, value)
            if type_ == e.EV_REL and code == e.REL_WHEEL:  # one per notch; the hi-res twin is skipped
                self.notify({"type": "scroll", "device": self.key})

    # Buttons

    def _button(self, code, value, now):
        if value == 2:  # autorepeat
            return
        name = BUTTON_NAMES[code]
        pressed = value == 1
        self.notify({"type": "button", "device": self.key, "button": name, "pressed": pressed})
        if name in LOCKED_BUTTONS:
            self.out.write(e.EV_KEY, code, value)
            return

        if pressed:
            cfg = button_config(self.profile, name)
            if self.hold is None and is_held(cfg):
                self.hold = Hold(code, now, cfg)
                return
            self.pressed[code] = cfg["click"]
            self._press(code, cfg["click"])
            return

        if self.hold and self.hold.code == code:
            hold, self.hold = self.hold, None
            if not hold.consumed:
                self._tap(code, hold.cfg["click"])
            return
        action = self.pressed.pop(code, None)
        if action is None:
            # Pressed before the grab: the press went out unmodified.
            self.out.write(e.EV_KEY, code, 0)
            return
        self._release(code, action)

    def _press(self, code, action):
        kind = action["type"]
        if kind == "default":
            self.out.write(e.EV_KEY, code, 1)
        elif kind == "button":
            self.out.write(e.EV_KEY, BUTTON_CODES[action["button"]], 1)
        elif kind == "precision":
            self.precision += 1
        elif kind == "keys":
            self.actions.press(action)
        elif kind != "disabled":
            self.actions.tap(action)

    def _release(self, code, action):
        kind = action["type"]
        if kind == "default":
            self.out.write(e.EV_KEY, code, 0)
        elif kind == "button":
            self.out.write(e.EV_KEY, BUTTON_CODES[action["button"]], 0)
        elif kind == "precision":
            self.precision = max(0, self.precision - 1)
        elif kind == "keys":
            self.actions.release(action)

    def _tap(self, code, action):
        kind = action["type"]
        if kind in ("default", "button"):
            target = code if kind == "default" else BUTTON_CODES[action["button"]]
            self.out.write(e.EV_KEY, target, 1)
            self.out.syn()
            self.out.write(e.EV_KEY, target, 0)
            self.out.syn()
        elif kind not in ("disabled", "precision"):
            self.actions.tap(action)

    # Motion and wheel

    def _motion(self, code, value, now):
        hold = self.hold
        if hold and hold.cfg["swipe"] and not hold.consumed:
            if code == e.REL_X:
                hold.dx += value
            else:
                hold.dy += value
            gesture = self.profile.get("gesture", DEFAULT_GESTURE)
            if (now - hold.since) * 1000 >= gesture.get("hold_ms", DEFAULT_GESTURE["hold_ms"]):
                direction = detect_swipe(hold.dx, hold.dy, gesture.get("threshold", DEFAULT_GESTURE["threshold"]))
                # Only bound directions commit: a long press that drifts
                # somewhere unbound still clicks on release.
                if direction in hold.cfg["swipe"]:
                    hold.consumed = True
                    self.notify({"type": "swipe", "device": self.key,
                                 "button": BUTTON_NAMES[hold.code], "direction": direction})
                    self._tap(hold.code, hold.cfg["swipe"][direction])

        if self.precision:
            factor = self.profile.get("precision", DEFAULT_PRECISION)
            scaled = value * factor + self.remainder[code]
            out = int(scaled)
            self.remainder[code] = scaled - out
            if out:
                self.out.write(e.EV_REL, code, out)
            return
        self.out.write(e.EV_REL, code, value)

    def _wheel(self, code, value):
        hold = self.hold
        hold.consumed = True
        if code != e.REL_WHEEL:
            return  # the high-resolution twin of the same turn
        direction = "up" if value > 0 else "down"
        action = hold.cfg["wheel"].get(direction)
        self.notify({"type": "wheel", "device": self.key,
                     "button": BUTTON_NAMES[hold.code], "direction": direction})
        if action:
            for _ in range(abs(value)):
                self._tap(hold.code, action)
