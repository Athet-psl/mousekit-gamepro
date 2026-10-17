"""Running actions that leave the mouse: KDE shortcuts, key combinations, commands."""

import logging
import queue
import subprocess
import threading

import evdev
from evdev import ecodes as e

from .keys import ALL_KEY_CODES, parse_combo

log = logging.getLogger("mousekit")

KGLOBALACCEL = "org.kde.kglobalaccel"
COMPONENT_IFACE = "org.kde.kglobalaccel.Component"


class ActionRunner:
    def __init__(self):
        self._keyboard = None
        self._shortcuts = queue.Queue()
        # D-Bus calls run on their own thread so a slow or hung kglobalaccel
        # can never stall the mouse event loop.
        threading.Thread(target=self._shortcut_worker, daemon=True, name="kglobalaccel").start()

    def close(self):
        if self._keyboard:
            self._keyboard.close()
            self._keyboard = None

    def tap(self, action):
        kind = action["type"]
        if kind == "keys":
            self.press(action)
            self.release(action)
        elif kind == "shortcut":
            self._shortcuts.put((action["component"], action["name"]))
        elif kind == "command":
            subprocess.Popen(["sh", "-c", action["command"]], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)

    def press(self, action):
        self._send_keys(action, 1)

    def release(self, action):
        self._send_keys(action, 0)

    def _send_keys(self, action, value):
        try:
            codes = parse_combo(action.get("combo", ""))
        except ValueError as err:
            log.warning("skipping key action: %s", err)
            return
        if self._keyboard is None:
            self._keyboard = evdev.UInput({e.EV_KEY: ALL_KEY_CODES}, name="Mousekit keys")
        for code in codes if value else reversed(codes):
            self._keyboard.write(e.EV_KEY, code, value)
        self._keyboard.syn()

    def _shortcut_worker(self):
        import dbus

        bus = None
        paths = {}
        while True:
            component, name = self._shortcuts.get()
            try:
                if bus is None:
                    bus = dbus.SessionBus()
                if component not in paths:
                    paths.update(component_paths(bus))
                obj = bus.get_object(KGLOBALACCEL, paths[component], introspect=False)
                obj.invokeShortcut(name, dbus_interface=COMPONENT_IFACE, timeout=2)
            except Exception as err:  # noqa: BLE001 - a failed action must not kill the worker
                log.warning("shortcut %s/%s failed: %s", component, name, err)
                bus = None
                paths.clear()


def component_paths(bus):
    """kglobalaccel component unique name -> D-Bus object path."""
    import dbus

    registry = bus.get_object(KGLOBALACCEL, "/kglobalaccel")
    paths = {}
    for path in registry.allComponents(dbus_interface="org.kde.KGlobalAccel"):
        props = dbus.Interface(bus.get_object(KGLOBALACCEL, path), "org.freedesktop.DBus.Properties")
        paths[str(props.Get(COMPONENT_IFACE, "uniqueName"))] = str(path)
    return paths
