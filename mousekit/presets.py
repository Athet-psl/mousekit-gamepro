"""Ready-made actions for the settings app, and human-readable action labels and icons."""

import sys

from .devices import BUTTON_NAMES

WINDOWS = sys.platform == "win32"


def shortcut(component, name):
    return {"type": "shortcut", "component": component, "name": name}


def keys(combo):
    return {"type": "keys", "combo": combo}


def command(text):
    return {"type": "command", "command": text}


# Windows has no global-shortcut service to call, so its presets are the system's own key combinations.
WINDOWS_GROUPS = [
    ("Virtual desktops", "virtual-desktops", [
        ("Desktop left", keys("Ctrl+Meta+Left"), "go-previous"),
        ("Desktop right", keys("Ctrl+Meta+Right"), "go-next"),
        ("Task view", keys("Meta+Tab"), "view-app-grid"),
        ("Show desktop", keys("Meta+D"), "virtual-desktops"),
        ("New desktop", keys("Ctrl+Meta+D"), "list-add"),
        ("Close desktop", keys("Ctrl+Meta+F4"), "window-close"),
    ]),
    ("Windows", "window", [
        ("Close window", keys("Alt+F4"), "window-close"),
        ("Maximize window", keys("Meta+Up"), "window-maximize"),
        ("Minimize window", keys("Meta+Down"), "window-minimize"),
        ("Previous window", keys("Alt+Tab"), "window-duplicate"),
        ("Window to next screen", keys("Meta+Shift+Right"), "window"),
        ("Snap left", keys("Meta+Left"), "go-previous"),
        ("Snap right", keys("Meta+Right"), "go-next"),
    ]),
    ("Media and sound", "media-playback-start", [
        ("Play / pause", keys("Media Play"), "media-playback-start"),
        ("Next track", keys("Media Next"), "media-skip-forward"),
        ("Previous track", keys("Media Previous"), "media-skip-backward"),
        ("Volume up", keys("Volume Up"), "audio-volume-high"),
        ("Volume down", keys("Volume Down"), "audio-volume-low"),
        ("Mute", keys("Volume Mute"), "audio-volume-muted"),
    ]),
    ("System", "preferences-system", [
        ("Search", keys("Meta+S"), "system-search"),
        ("Screenshot of an area", keys("Meta+Shift+S"), "camera-photo"),
        ("Clipboard history", keys("Meta+V"), "edit-paste"),
        ("File Explorer", keys("Meta+E"), "folder-open"),
        ("Task Manager", keys("Ctrl+Shift+Esc"), "computer"),
        ("Lock screen", command("rundll32.exe user32.dll,LockWorkStation"), "system-lock-screen"),
    ]),
]

# The DPI buttons' actions when Mousekit takes them over.
DPI_DEFAULTS = (
    {"DPI_UP": keys("Ctrl+Meta+Right"), "DPI_DOWN": keys("Ctrl+Meta+Left")} if WINDOWS else
    {"DPI_UP": shortcut("kwin", "Switch One Desktop to the Right"),
     "DPI_DOWN": shortcut("kwin", "Switch One Desktop to the Left")})

# (group, group icon, [(label, action, icon)])
KDE_GROUPS = [
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

PRESET_GROUPS = WINDOWS_GROUPS if WINDOWS else KDE_GROUPS

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
    preset = _preset(action) if kind in ("keys", "command", "shortcut") else None
    if preset:
        return preset[0]
    if kind == "keys":
        return action["combo"]
    if kind == "command":
        return action["command"]
    return (catalog or {}).get((action["component"], action["name"])) or action["name"]


def action_icon(action):
    if not action:
        return "list-add"
    kind = action["type"]
    preset = _preset(action) if kind in ("keys", "command", "shortcut") else None
    if preset:
        return preset[1]
    if kind == "shortcut":
        return "kde"
    return {
        "default": "input-mouse",
        "disabled": "dialog-cancel",
        "precision": "crosshairs",
        "button": "input-mouse",
        "keys": "input-keyboard",
        "command": "utilities-terminal",
    }.get(kind, "input-mouse")


assert set(BUTTON_LABELS) == set(BUTTON_NAMES.values())
