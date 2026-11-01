"""Linux input event codes, on every platform.

Mousekit describes buttons, motion and keys with the kernel's evdev codes
everywhere: the engine, the config and the key combinations. Linux gets them
from python-evdev; elsewhere (Windows) the subset Mousekit uses is defined
here with the same values, which are fixed kernel ABI (linux/input-event-codes.h).
"""

try:
    from evdev import ecodes  # noqa: F401
except ImportError:  # not Linux
    import types

    _CODES = {
        "EV_SYN": 0x00, "EV_KEY": 0x01, "EV_REL": 0x02, "EV_ABS": 0x03, "EV_MSC": 0x04, "EV_FF": 0x15,
        "REL_X": 0x00, "REL_Y": 0x01, "REL_HWHEEL": 0x06, "REL_WHEEL": 0x08,
        "REL_WHEEL_HI_RES": 0x0B, "REL_HWHEEL_HI_RES": 0x0C,
        "BTN_LEFT": 0x110, "BTN_RIGHT": 0x111, "BTN_MIDDLE": 0x112, "BTN_SIDE": 0x113, "BTN_EXTRA": 0x114,
        "BTN_FORWARD": 0x115, "BTN_BACK": 0x116, "BTN_TASK": 0x117,
        "KEY_ESC": 1, "KEY_MINUS": 12, "KEY_EQUAL": 13, "KEY_BACKSPACE": 14, "KEY_TAB": 15,
        "KEY_LEFTBRACE": 26, "KEY_RIGHTBRACE": 27, "KEY_ENTER": 28, "KEY_LEFTCTRL": 29,
        "KEY_SEMICOLON": 39, "KEY_APOSTROPHE": 40, "KEY_GRAVE": 41, "KEY_LEFTSHIFT": 42, "KEY_BACKSLASH": 43,
        "KEY_COMMA": 51, "KEY_DOT": 52, "KEY_SLASH": 53, "KEY_RIGHTSHIFT": 54, "KEY_KPASTERISK": 55,
        "KEY_LEFTALT": 56, "KEY_SPACE": 57, "KEY_CAPSLOCK": 58, "KEY_NUMLOCK": 69, "KEY_SCROLLLOCK": 70,
        "KEY_F11": 87, "KEY_F12": 88, "KEY_KPENTER": 96, "KEY_RIGHTCTRL": 97, "KEY_KPSLASH": 98,
        "KEY_SYSRQ": 99, "KEY_RIGHTALT": 100, "KEY_HOME": 102, "KEY_UP": 103, "KEY_PAGEUP": 104,
        "KEY_LEFT": 105, "KEY_RIGHT": 106, "KEY_END": 107, "KEY_DOWN": 108, "KEY_PAGEDOWN": 109,
        "KEY_INSERT": 110, "KEY_DELETE": 111, "KEY_MUTE": 113, "KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115,
        "KEY_POWER": 116, "KEY_PAUSE": 119, "KEY_LEFTMETA": 125, "KEY_RIGHTMETA": 126, "KEY_COMPOSE": 127,
        "KEY_STOP": 128, "KEY_CALC": 140, "KEY_SLEEP": 142, "KEY_BACK": 158, "KEY_FORWARD": 159,
        "KEY_NEXTSONG": 163, "KEY_PLAYPAUSE": 164, "KEY_PREVIOUSSONG": 165, "KEY_STOPCD": 166,
        "KEY_REWIND": 168, "KEY_REFRESH": 173, "KEY_PLAYCD": 200, "KEY_PAUSECD": 201,
        "KEY_FASTFORWARD": 208, "KEY_MICMUTE": 248,
    }
    for _i, _c in enumerate("1234567890"):
        _CODES[f"KEY_{_c}"] = 2 + _i
    for _row, _start in (("QWERTYUIOP", 16), ("ASDFGHJKL", 30), ("ZXCVBNM", 44)):
        for _i, _c in enumerate(_row):
            _CODES[f"KEY_{_c}"] = _start + _i
    for _i in range(10):
        _CODES[f"KEY_F{_i + 1}"] = 59 + _i
    for _i in range(12):
        _CODES[f"KEY_F{_i + 13}"] = 183 + _i

    ecodes = types.SimpleNamespace(**_CODES)
    ecodes.KEY = {v: k for k, v in _CODES.items() if k.startswith("KEY_")}
    ecodes.BTN = {v: k for k, v in _CODES.items() if k.startswith("BTN_")}
