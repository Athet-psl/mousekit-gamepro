"""mousekitd: grabs the mice enabled in the config and replays them through uinput mirrors.

Each managed mouse is grabbed exclusively; its events go through an Engine
and out of a virtual mirror device with the same IDs, so libinput and KDE keep
treating it like the hardware. Live events (button presses, swipes) are
broadcast as JSON lines on a Unix socket for the settings app.
"""

import json
import logging
import os
import selectors
import signal
import socket
import sys
import threading
import time
from collections import deque

import evdev
from evdev import ecodes as e

from . import config, devices, effects, updates, vendor
from .actions import ActionRunner
from .engine import Engine

log = logging.getLogger("mousekit")

SCAN_INTERVAL = 2.0


class Held(Exception):
    """A button or key of the device was down, so it wasn't grabbed."""


def grab_released(dev):
    """Grab `dev` unless one of its buttons or keys is down; then raise Held.

    A press that reached KDE before the grab never gets its release: KDE keeps
    the button held (a stuck drag, clicks do nothing) until the mouse is
    replugged. So a device in use is left alone until a scan finds it released.
    """
    dev.grab()
    if dev.active_keys():
        dev.ungrab()
        raise Held


class Mirror:
    """The uinput twin of a grabbed mouse."""

    def __init__(self, dev):
        caps = {t: c for t, c in dev.capabilities().items() if t not in (e.EV_SYN, e.EV_FF)}
        # Every mouse button exists on the mirror, so any button can be
        # remapped to any other.
        caps[e.EV_KEY] = sorted(set(caps.get(e.EV_KEY, [])) | set(devices.BUTTON_NAMES))
        info = dev.info
        self.uinput = evdev.UInput(
            caps, name=f"{devices.VIRTUAL_PREFIX}: {dev.name.strip()}",
            vendor=info.vendor, product=info.product, version=info.version, bustype=info.bustype)

    def write(self, type_, code, value):
        self.uinput.write(type_, code, value)

    def syn(self):
        self.uinput.syn()

    def close(self):
        self.uinput.close()


class EffectRunner:
    """Streams one of Mousekit's own lighting effects into a mouse's DPI colour slots."""

    def __init__(self, key, node, light):
        self.key = key
        self.node = node
        self.light = light
        self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
        self.start = time.monotonic()
        self.clicks = deque(maxlen=16)
        self.sent = None
        self.next_frame = 0.0
        vendor.send(self.fd, vendor.stream_start_packet())

    def tick(self, now):
        clicks = [when - self.start for when in self.clicks]
        rgb = effects.to_device(effects.colour(self.light, now - self.start, clicks))
        packets = vendor.slot_packets(rgb, effects.SLOTS)
        if packets != self.sent:  # every slot, so a DPI change keeps the effect's colour
            for packet in packets:
                vendor.send(self.fd, packet, delay=0.0005)
            self.sent = packets
        self.next_frame = now + 1 / effects.FPS

    def fileno(self):
        return self.fd

    def readable(self):
        """Input reports on the vendor interface: buttons programmed as media keys, DPI buttons."""
        while True:
            try:
                report = os.read(self.fd, 64)
            except BlockingIOError:
                return
            dpi = vendor.parse_input(report)
            if vendor.is_key_press(report) or (dpi and dpi[0] == "dpi-press"):
                self.click()

    def refresh(self):
        """Put the mouse back into the streamed mode and resend the colour."""
        vendor.send(self.fd, vendor.stream_start_packet())
        self.sent = None
        self.next_frame = 0.0

    def click(self, kind="button"):
        if kind == "scroll" and not self.light.get("on_scroll", True):
            return
        self.clicks.append(time.monotonic())
        self.next_frame = 0.0

    def stop(self):
        os.close(self.fd)


# Keys the GM500W's buttons send through its keyboard interface (as programmed in the mouse) -> button names.
KEY_BUTTONS = {
    e.KEY_FASTFORWARD: "DPI_UP",     # DPI+ after Mousekit remaps the DPI buttons
    e.KEY_REWIND: "DPI_DOWN",        # DPI-
    e.KEY_PLAYPAUSE: "FIRE",         # Fire, programmed as play/pause
    e.KEY_NEXTSONG: "FORWARD_KEY",   # Forward, programmed as next track
}


class KeyInterface:
    """A mouse's keyboard interface, grabbed so the keys its buttons send can be remapped.

    Keys without a Mousekit action go out unchanged through a mirror device.
    """

    def __init__(self, key, node, daemon):
        self.key = key
        self.node = node
        self.daemon = daemon
        self.dev = evdev.InputDevice(node)
        try:
            grab_released(self.dev)
            self.mirror = evdev.UInput.from_device(self.dev, name=f"{devices.VIRTUAL_PREFIX}: {self.dev.name.strip()}")
        except (Held, OSError):
            self.dev.close()  # also ends the grab
            raise
        self.pressed = {}  # key code -> action taken over at press (None: passed through)

    def fileno(self):
        return self.dev.fileno()

    def handle(self, event):
        name = KEY_BUTTONS.get(event.code) if event.type == e.EV_KEY else None
        if name is None:
            self.mirror.write(event.type, event.code, event.value)
            return
        if event.value == 2:  # autorepeat: only for keys passed through
            if self.pressed.get(event.code) is None:
                self.mirror.write(event.type, event.code, event.value)
            return
        pressed = event.value == 1
        self.daemon.broadcast({"type": "button", "device": self.key, "button": name, "pressed": pressed})
        if pressed:
            profile = self.daemon.config["devices"].get(self.key) or {}
            action = profile.get("buttons", {}).get(name, {}).get("click")
            if not action or action["type"] == "default":
                action = None
            self.pressed[event.code] = action
            if action is None:
                self.mirror.write(e.EV_KEY, event.code, 1)
            else:
                self._run(action, True)
        else:
            action = self.pressed.pop(event.code, None)
            if action is None:
                self.mirror.write(e.EV_KEY, event.code, 0)
            else:
                self._run(action, False)

    def _run(self, action, pressed):
        kind = action["type"]
        if kind == "keys":
            (self.daemon.actions.press if pressed else self.daemon.actions.release)(action)
        elif kind == "button":
            mouse = next((m for m in self.daemon.managed.values() if m.info.key == self.key), None)
            if mouse:
                mouse.mirror.write(e.EV_KEY, devices.BUTTON_CODES[action["button"]], int(pressed))
                mouse.mirror.syn()
        elif pressed and kind not in ("disabled", "precision"):
            self.daemon.actions.tap(action)

    def readable(self):
        for event in self.dev.read():
            self.handle(event)

    def close(self):
        try:
            self.dev.ungrab()
        except OSError:
            pass
        self.dev.close()
        self.mirror.close()


class Managed:
    def __init__(self, info, dev, mirror, engine):
        self.info = info
        self.dev = dev
        self.mirror = mirror
        self.engine = engine


class Daemon:
    def __init__(self):
        self.selector = selectors.DefaultSelector()
        self.actions = ActionRunner()
        self.config = config.load()
        self.config_mtime = self._config_mtime()
        self.managed = {}   # event node -> Managed
        self.lit = set()    # vendor hidraw nodes whose saved lighting was already restored
        self.effects = {}   # vendor hidraw node -> EffectRunner
        self.key_ifaces = {}  # keyboard-interface node -> KeyInterface
        self.clients = []
        self.server = self._listen()

    # Live-event socket

    def _listen(self):
        path = config.SOCKET_PATH
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(4)
        server.setblocking(False)
        self.selector.register(server, selectors.EVENT_READ, self._accept)
        return server

    def _accept(self, server):
        conn, _ = server.accept()
        conn.setblocking(False)
        self.clients.append(conn)
        self.selector.register(conn, selectors.EVENT_READ, self._client_readable)
        self._send(conn, self._status())

    def _client_readable(self, conn):
        try:
            data = conn.recv(4096)
        except OSError:
            data = b""
        if not data:
            self._drop_client(conn)

    def _drop_client(self, conn):
        if conn in self.clients:
            self.clients.remove(conn)
            self.selector.unregister(conn)
            conn.close()

    def _send(self, conn, event):
        try:
            conn.send((json.dumps(event) + "\n").encode())
        except OSError:  # gone, or too slow to keep up
            self._drop_client(conn)

    def broadcast(self, event):
        kind = event.get("type")
        if (kind == "button" and event.get("pressed")) or kind == "scroll":
            for runner in self.effects.values():
                if runner.key == event.get("device"):
                    runner.click(kind)
        for conn in list(self.clients):
            self._send(conn, event)

    def _status(self):
        return {"type": "status", "managed": sorted({m.info.key for m in self.managed.values()})}

    # Devices

    def _config_mtime(self):
        try:
            return config.CONFIG_PATH.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def check_config(self):
        mtime = self._config_mtime()
        if mtime == self.config_mtime:
            return False
        self.config_mtime = mtime
        self.config = config.load()
        for managed in self.managed.values():
            managed.engine.set_profile(self.config["devices"].get(managed.info.key))
        log.info("config reloaded")
        return True

    def rescan(self):
        present = {}
        for info in devices.scan():
            profile = self.config["devices"].get(info.key)
            if profile and profile.get("enabled") and info.accessible:
                present[info.node] = info
        changed = False
        for node in list(self.managed):
            if node not in present:
                self.release(node)
                changed = True
        for node, info in present.items():
            if node not in self.managed:
                changed |= self.grab(info)
        if changed:
            self.broadcast(self._status())
        self.sync_key_interfaces()
        self.sync_lighting()

    def sync_key_interfaces(self):
        """Grab the keyboard interfaces of managed mice, release the rest."""
        wanted = {}
        for key in {m.info.key for m in self.managed.values()}:
            for node in devices.key_interfaces(key):
                wanted[node] = key
        for node in list(self.key_ifaces):
            if node not in wanted:
                self._release_keys(node)
        for node, key in wanted.items():
            if node in self.key_ifaces:
                continue
            try:
                iface = KeyInterface(key, node, self)
            except Held:
                continue  # taken at a later scan, once released
            except OSError as err:
                log.warning("cannot take the keys of %s (%s): %s", key, node, err)
                continue
            self.key_ifaces[node] = iface
            self.selector.register(iface, selectors.EVENT_READ, self._keys_readable)
            log.info("managing keys of %s (%s)", key, node)

    def _keys_readable(self, iface):
        try:
            iface.readable()
        except OSError as err:  # unplugged
            log.info("lost keys of %s: %s", iface.key, err)
            self._release_keys(iface.node)

    def _release_keys(self, node):
        iface = self.key_ifaces.pop(node)
        self.selector.unregister(iface)
        iface.close()

    def sync_lighting(self):
        """Run Mousekit effects where chosen; re-send firmware lighting once per connection.

        Firmware lighting is live-only (nothing is committed to the mouse), so a
        replug resets it; Mousekit effects need the daemon streaming all the time.
        """
        present = {}
        for key, profile in self.config["devices"].items():
            light = profile.get("lighting") or {}
            if not light.get("restore") or ("mode" not in light and "effect" not in light):
                continue
            node = vendor.find_hidraw(key)
            if node:
                present[node] = (key, light)
        for node, runner in list(self.effects.items()):
            entry = present.get(node)
            if entry and entry[1].get("engine") == "mousekit":
                runner.light = entry[1]
                runner.refresh()  # resend the stream in case something else changed the lighting
                continue
            self._stop_effect(node)
            self.lit.discard(node)  # re-send firmware lighting over the last streamed frame
            log.info("stopped effect on %s", runner.key)
        for node, (key, light) in present.items():
            if light.get("engine") == "mousekit":
                if node not in self.effects:
                    try:
                        runner = EffectRunner(key, node, light)
                    except OSError as err:
                        log.warning("cannot start effect on %s: %s", node, err)
                        continue
                    self.effects[node] = runner
                    self.selector.register(runner, selectors.EVENT_READ, lambda r: self._effect_input(r))
                    log.info("effect %s on %s (%s)", light.get("effect"), key, node)
                continue
            if node in self.lit or "mode" not in light:
                continue
            try:
                fd = os.open(node, os.O_RDWR)
                try:
                    vendor.apply_lighting(fd, light)
                finally:
                    os.close(fd)
            except OSError as err:
                log.warning("cannot restore lighting on %s: %s", node, err)
                continue
            self.lit.add(node)
            log.info("restored lighting on %s (%s)", key, node)
        self.lit &= set(present)

    def _stop_effect(self, node):
        runner = self.effects.pop(node)
        self.selector.unregister(runner)
        runner.stop()

    def _effect_input(self, runner):
        try:
            runner.readable()
        except OSError as err:  # unplugged
            log.info("effect on %s ended: %s", runner.key, err)
            self._stop_effect(runner.node)

    def tick_effects(self):
        now = time.monotonic()
        for node, runner in list(self.effects.items()):
            if now < runner.next_frame:
                continue
            try:
                runner.tick(now)
            except OSError as err:  # unplugged
                log.info("effect on %s ended: %s", runner.key, err)
                self._stop_effect(node)

    def next_timeout(self):
        if not self.effects:
            return 1.0
        wait = min(runner.next_frame for runner in self.effects.values()) - time.monotonic()
        return max(0.0, min(1.0, wait))

    def grab(self, info):
        try:
            dev = evdev.InputDevice(info.node)
        except OSError as err:
            log.warning("cannot manage %s (%s): %s", info.name, info.node, err)
            return False
        try:
            grab_released(dev)
            mirror = Mirror(dev)
        except Held:
            dev.close()
            return False  # grabbed at a later scan, once released
        except OSError as err:
            dev.close()  # also ends the grab
            log.warning("cannot manage %s (%s): %s", info.name, info.node, err)
            return False
        engine = Engine(mirror, self.actions, self.broadcast, info.key)
        engine.set_profile(self.config["devices"].get(info.key))
        self.managed[info.node] = Managed(info, dev, mirror, engine)
        self.selector.register(dev, selectors.EVENT_READ, self._device_readable)
        log.info("managing %s (%s, %s)", info.name, info.key, info.node)
        return True

    def release(self, node):
        managed = self.managed.pop(node)
        managed.engine.reset()
        self.selector.unregister(managed.dev)
        try:
            managed.dev.ungrab()
        except OSError:
            pass
        managed.dev.close()
        managed.mirror.close()
        log.info("released %s (%s)", managed.info.name, node)

    def _device_readable(self, dev):
        managed = self.managed.get(dev.path)
        try:
            for event in dev.read():
                managed.engine.handle(event.type, event.code, event.value)
        except OSError as err:  # unplugged
            log.info("lost %s: %s", managed.info.name, err)
            self.release(dev.path)
            self.broadcast(self._status())

    # Main loop

    def run(self):
        self.rescan()
        last_scan = time.monotonic()
        while True:
            for key, _ in self.selector.select(timeout=self.next_timeout()):
                key.data(key.fileobj)
            self.tick_effects()
            now = time.monotonic()
            if self.check_config() or now - last_scan >= SCAN_INTERVAL:
                self.rescan()
                last_scan = now

    def shutdown(self):
        for node in list(self.managed):
            self.release(node)
        for node in list(self.effects):
            self._stop_effect(node)
        for node in list(self.key_ifaces):
            self._release_keys(node)
        self.actions.close()
        self.server.close()
        try:
            config.SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


class UpdateWatcher(threading.Thread):
    """Checks GitHub for a newer release every hour and shows a notification once per version."""

    FIRST_CHECK = 120  # seconds after start: not in the middle of logging in

    def __init__(self):
        super().__init__(name="updates", daemon=True)
        self.stopped = threading.Event()

    def run(self):
        wait = self.FIRST_CHECK
        while not self.stopped.wait(wait):
            wait = updates.CHECK_INTERVAL
            if not config.load().get("check_updates", True):
                continue
            try:
                newer = updates.newer_releases(updates.fetch_releases())
            except (OSError, ValueError) as err:
                log.info("update check failed: %s", err)
                continue
            if not newer or not updates.deb_asset(newer[0]):
                continue
            version = updates.release_version(newer[0])
            if updates.last_notified() != version:
                log.info("update %s available", version)
                updates.set_notified(version)
                updates.notify_update(version)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if updates.installed_from_package():  # a source checkout updates with git
        UpdateWatcher().start()
    daemon = Daemon()
    try:
        daemon.run()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.shutdown()


if __name__ == "__main__":
    main()
