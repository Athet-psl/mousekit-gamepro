"""Ready-made actions for the settings app, and human-readable action labels and icons."""

from .devices import BUTTON_NAMES


def shortcut(component, name):
    return {"type": "shortcut", "component": component, "name": name}


# (group, group icon, [(label, action, icon)])
PRESET_GROUPS = [
    ("Virtual desktops", "virtual-desktops", [
        ("Desktop left", shortcut("kwin", "Switch One Desktop to the Left"), "go-previous"),
        ("Desktop right", shortcut("kwin", "Switch One Desktop to the Right"), "go-next"),
        ("Overview", shortcut("kwin", "Overview"), "view-app-grid"),
        ("Desktop grid", shortcut("kwin", "Grid View"), "view-grid"),
        ("Show desktop", shortcut("kwin", "Show Desktop"), "virtual-desktops"),
        ("Windows on this desktop", shortcut("kwin", "Expose"), "window-duplicate"),
        ("Windows on all desktops", shortcut("kwin", "ExposeAll"), "window-duplicate"),
        ("Windows of this app", shortcut("kwin", "ExposeClass"), "window-duplicate"),
    ]),
    ("Windows", "window", [
        ("Close window", shortcut("kwin", "Window Close"), "window-close"),
        ("Maximize window", shortcut("kwin", "Window Maximize"), "window-maximize"),
        ("Minimize window", shortcut("kwin", "Window Minimize"), "window-minimize"),
        ("Fullscreen", shortcut("kwin", "Window Fullscreen"), "view-fullscreen"),
        ("Window to desktop left", shortcut("kwin", "Window One Desktop to the Left"), "go-previous"),
        ("Window to desktop right", shortcut("kwin", "Window One Desktop to the Right"), "go-next"),
        ("Window to next screen", shortcut("kwin", "Window to Next Screen"), "window"),
        ("Tile left", shortcut("kwin", "Window Quick Tile Left"), "go-previous"),
        ("Tile right", shortcut("kwin", "Window Quick Tile Right"), "go-next"),
    ]),
    ("Media and sound", "media-playback-start", [
        ("Play / pause", shortcut("mediacontrol", "playpausemedia"), "media-playback-start"),
        ("Next track", shortcut("mediacontrol", "nextmedia"), "media-skip-forward"),
        ("Previous track", shortcut("mediacontrol", "previousmedia"), "media-skip-backward"),
        ("Volume up", shortcut("kmix", "increase_volume"), "audio-volume-high"),
        ("Volume down", shortcut("kmix", "decrease_volume"), "audio-volume-low"),
        ("Volume up 1%", shortcut("kmix", "increase_volume_small"), "audio-volume-high"),
        ("Volume down 1%", shortcut("kmix", "decrease_volume_small"), "audio-volume-low"),
        ("Mute", shortcut("kmix", "mute"), "audio-volume-muted"),
        ("Mute microphone", shortcut("kmix", "mic_mute"), "microphone-sensitivity-muted"),
    ]),
    ("System", "preferences-system", [
        ("KRunner", shortcut("org.kde.krunner.desktop", "_launch"), "krunner"),
        ("Screenshot of an area", shortcut("org.kde.spectacle.desktop", "RectangularRegionScreenShot"), "spectacle"),
        ("Record an area of the screen", shortcut("org.kde.spectacle.desktop", "RecordRegion"), "spectacle"),
        ("Clipboard at the cursor", shortcut("plasmashell", "show-on-mouse-pos"), "edit-paste"),
        ("Lock screen", shortcut("ksmserver", "Lock Session"), "system-lock-screen"),
    ]),
]

BUTTON_LABELS = {
    "BTN_LEFT": "Left button",
    "BTN_RIGHT": "Right button",
    "BTN_MIDDLE": "Wheel",
    "BTN_SIDE": "Back",
    "BTN_EXTRA": "Forward",
    "BTN_FORWARD": "Extra forward",
    "BTN_BACK": "Extra back",
    "BTN_TASK": "Task button",
}

SWIPE_LABELS = {"left": "←", "right": "→", "up": "↑", "down": "↓"}
SWIPE_NAMES = {"left": "Left", "right": "Right", "up": "Up", "down": "Down"}
WHEEL_NAMES = {"up": "Wheel up", "down": "Wheel down"}


def _same(a, b):
    keys = ("type", "component", "name", "button", "combo", "command")
    return all(a.get(k) == b.get(k) for k in keys)


def _preset(action):
    for _, group_icon, presets in PRESET_GROUPS:
        for label, preset, icon in presets:
            if _same(action, preset):
                return label, icon or group_icon
    return None


def action_label(action, catalog=None):
    """Short text for an action; catalog maps (component, name) -> friendly name."""
    if not action:
        return "Not set"
    kind = action["type"]
    if kind == "default":
        return "Default"
    if kind == "disabled":
        return "Nothing"
    if kind == "precision":
        return "Precision mode"
    if kind == "button":
        return BUTTON_LABELS.get(action["button"], action["button"])
    if kind == "keys":
        return action["combo"]
    if kind == "command":
        return action["command"]
    preset = _preset(action)
    if preset:
        return preset[0]
    return (catalog or {}).get((action["component"], action["name"])) or action["name"]


def action_icon(action):
    if not action:
        return "list-add"
    kind = action["type"]
    if kind == "shortcut":
        preset = _preset(action)
        return preset[1] if preset else "kde"
    return {
        "default": "input-mouse",
        "disabled": "dialog-cancel",
        "precision": "crosshairs",
        "button": "input-mouse",
        "keys": "input-keyboard",
        "command": "utilities-terminal",
    }.get(kind, "input-mouse")


assert set(BUTTON_LABELS) == set(BUTTON_NAMES.values())
