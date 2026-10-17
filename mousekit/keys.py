"""Key combinations in Qt's portable text form ("Meta+Ctrl+Left") as evdev key codes."""

from evdev import ecodes as e

MODIFIERS = {
    "Ctrl": e.KEY_LEFTCTRL,
    "Alt": e.KEY_LEFTALT,
    "Shift": e.KEY_LEFTSHIFT,
    "Meta": e.KEY_LEFTMETA,
}

NAMED = {
    "Esc": e.KEY_ESC, "Tab": e.KEY_TAB, "Backtab": e.KEY_TAB, "Backspace": e.KEY_BACKSPACE,
    "Return": e.KEY_ENTER, "Enter": e.KEY_KPENTER, "Ins": e.KEY_INSERT, "Del": e.KEY_DELETE,
    "Pause": e.KEY_PAUSE, "Print": e.KEY_SYSRQ, "SysReq": e.KEY_SYSRQ,
    "Home": e.KEY_HOME, "End": e.KEY_END, "PgUp": e.KEY_PAGEUP, "PgDown": e.KEY_PAGEDOWN,
    "Left": e.KEY_LEFT, "Up": e.KEY_UP, "Right": e.KEY_RIGHT, "Down": e.KEY_DOWN,
    "CapsLock": e.KEY_CAPSLOCK, "NumLock": e.KEY_NUMLOCK, "ScrollLock": e.KEY_SCROLLLOCK,
    "Menu": e.KEY_COMPOSE, "Space": e.KEY_SPACE,
    "-": e.KEY_MINUS, "=": e.KEY_EQUAL, "[": e.KEY_LEFTBRACE, "]": e.KEY_RIGHTBRACE,
    ";": e.KEY_SEMICOLON, "'": e.KEY_APOSTROPHE, "`": e.KEY_GRAVE, "\\": e.KEY_BACKSLASH,
    ",": e.KEY_COMMA, ".": e.KEY_DOT, "/": e.KEY_SLASH,
    "Media Play": e.KEY_PLAYPAUSE, "Media Pause": e.KEY_PAUSECD, "Toggle Media Play/Pause": e.KEY_PLAYPAUSE,
    "Media Stop": e.KEY_STOPCD, "Media Next": e.KEY_NEXTSONG, "Media Previous": e.KEY_PREVIOUSSONG,
    "Volume Up": e.KEY_VOLUMEUP, "Volume Down": e.KEY_VOLUMEDOWN, "Volume Mute": e.KEY_MUTE,
    "Back": e.KEY_BACK, "Forward": e.KEY_FORWARD, "Refresh": e.KEY_REFRESH,
    "Calculator": e.KEY_CALC, "Sleep": e.KEY_SLEEP,
}

# Shifted symbols as Qt reports them (e.g. "Ctrl+Shift+!") -> unshifted key.
SHIFTED = {
    "!": e.KEY_1, "@": e.KEY_2, "#": e.KEY_3, "$": e.KEY_4, "%": e.KEY_5, "^": e.KEY_6,
    "&": e.KEY_7, "*": e.KEY_8, "(": e.KEY_9, ")": e.KEY_0, "_": e.KEY_MINUS, "+": e.KEY_EQUAL,
    "{": e.KEY_LEFTBRACE, "}": e.KEY_RIGHTBRACE, ":": e.KEY_SEMICOLON, '"': e.KEY_APOSTROPHE,
    "~": e.KEY_GRAVE, "|": e.KEY_BACKSLASH, "<": e.KEY_COMMA, ">": e.KEY_DOT, "?": e.KEY_SLASH,
}


def _key_code(token):
    if token in NAMED:
        return NAMED[token]
    if len(token) == 1 and token.isascii() and token.isalnum():
        return getattr(e, f"KEY_{token.upper()}")
    if token.startswith("F") and token[1:].isdigit() and 1 <= int(token[1:]) <= 24:
        return getattr(e, f"KEY_{token}")
    raise ValueError(f"unsupported key: {token}")


def parse_combo(text):
    """Key codes to press in order (modifiers first) for one combination.

    Raises ValueError for anything that can't be typed on a plain keyboard.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty key combination")
    # "Ctrl++" means Ctrl and the plus key: split off the last key first.
    if text.endswith("++"):
        head, last = text[:-2], "+"
    elif "+" in text:
        head, _, last = text.rpartition("+")
    else:
        head, last = "", text
    codes = []
    for token in filter(None, head.split("+")):
        if token not in MODIFIERS:
            raise ValueError(f"unknown modifier: {token}")
        codes.append(MODIFIERS[token])
    if last in MODIFIERS:
        raise ValueError("a combination needs a non-modifier key")
    if last in SHIFTED:
        if MODIFIERS["Shift"] not in codes:
            codes.append(MODIFIERS["Shift"])
        codes.append(SHIFTED[last])
    else:
        codes.append(_key_code(last))
    return codes


# Every code a virtual keyboard may need to send.
ALL_KEY_CODES = sorted(set(range(e.KEY_ESC, e.KEY_MICMUTE + 1)) | set(range(e.KEY_F13, e.KEY_F24 + 1)))
