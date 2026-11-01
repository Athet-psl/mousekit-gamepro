"""mousekitd on Windows: the same service as on Linux, built on hooks instead of grabs.

- Mice: a low-level mouse hook sees every button and wheel event. For a
  managed mouse (the one raw input says moved last) it runs through that
  mouse's Engine; what the engine sends back unchanged passes on, anything
  else is swallowed and the engine's events are injected with SendInput.
  Raw motion feeds the engine's swipe detection. Precision mode lowers the
  pointer speed while held, since motion itself isn't rewritten.
- GM500W keys: the buttons programmed in the mouse as media keys are read
  from its HID collections. Windows also acts on the media keys, so the
  keyboard hook holds back the matching key and drops it if the mouse sent
  it, or lets it through late if it came from a keyboard.
- Lighting and Mousekit's effects as on Linux; live events for the app go
  over 127.0.0.1, with a secret from config.SOCKET_PATH.
"""

import json
import logging
import logging.handlers
import os
import re
import secrets
import selectors
import socket
import sys
import threading
import time
from collections import deque

from . import config, devices, updates, vendor, winhook
from .actions import WindowsActionRunner
from .codes import ecodes as e
from .engine import Engine
from .lightstream import EffectRunner, apply_once

log = logging.getLogger("mousekit")

SCAN_INTERVAL = 2.0
MUTEX_NAME = "Local\\MousekitService"
SPEED_PATH = config.LOCAL_DIR / "pointer-speed"   # the speed to restore if precision mode was cut short
KEY_HOLD = 0.25  # how long a media key waits to see whether the mouse sent it

# Consumer usages the GM500W's programmed buttons send -> button names (as on Linux: daemon.KEY_BUTTONS).
USAGE_BUTTONS = {0xB3: "DPI_UP", 0xB4: "DPI_DOWN", 0xCD: "FIRE", 0xB5: "FORWARD_KEY"}
# The virtual keys Windows makes of some of them, which reach applications unless held back.
USAGE_VKS = {0xCD: 0xB3, 0xB5: 0xB0, 0xB6: 0xB1, 0xB7: 0xB2, 0xE9: 0xAF, 0xEA: 0xAE, 0xE2: 0xAD}
VK_USAGES = {vk: usage for usage, vk in USAGE_VKS.items()}


def key_of_path(path):
    """"vvvv:pppp" from a HID or raw input device path, or None."""
    match = re.search(r"vid[_&]([0-9a-f]{4,8})&pid[_&]([0-9a-f]{4})", path or "", re.IGNORECASE)
    if not match:
        return None
    return f"{int(match.group(1), 16):04x}:{match.group(2).lower()}"


class Output:
    """An engine's output: collected per input, then passed, dropped or injected by the hook."""

    def __init__(self):
        self.events = []

    def write(self, type_, code, value):
        self.events.append((type_, code, value))

    def syn(self):
        pass

    def take(self):
        events, self.events = self.events, []
        return events


class Managed:
    def __init__(self, info, engine, out):
        self.info = info
        self.engine = engine
        self.out = out


class KeyReader(threading.Thread):
    """Reads a GM500W's input collections: programmed keys and DPI button events."""

    def __init__(self, service, key, node):
        super().__init__(daemon=True, name=f"keys {key}")
        self.service = service
        self.key = key
        self.node = node
        self.channel = vendor.open_channel(node)
        self.stopped = threading.Event()
        self.pressed = None  # (usage, action) of the key down now

    def run(self):
        threads = [threading.Thread(target=self._read, args=(device,), daemon=True) for device in self.channel.inputs]
        for thread in threads:
            thread.start()
        self.stopped.wait()
        for thread in threads:
            thread.join()  # each read times out within half a second
        self.channel.close()

    def _read(self, device):
        while not self.stopped.is_set():
            try:
                report = device.read(0.5)
            except OSError as err:
                if not self.stopped.is_set():
                    log.info("lost keys of %s: %s", self.key, err)
                    self.stopped.set()
                return
            if report:
                self.service.vendor_report(self, report)

    def stop(self):
        self.stopped.set()


class Service:
    def __init__(self):
        self.lock = threading.RLock()
        self.actions = WindowsActionRunner()
        self.config = config.load()
        self.config_mtime = self._config_mtime()
        self.managed = {}       # key -> Managed
        self.readers = {}       # key -> KeyReader
        self.effects = {}       # vendor node -> EffectRunner
        self.lit = set()        # vendor nodes whose saved lighting was already restored
        self.clients = []       # authenticated sockets
        self.pending = {}       # vk -> {"usage", "since", "claimed", "up"}: media keys held back
        self.mouse_keys = deque(maxlen=16)  # (usage, time) of keys the mouse sent
        self.base_speed = None  # pointer speed before precision mode
        self.stopping = threading.Event()
        self.hooks = winhook.Hooks(self.on_mouse, self.on_key, self.on_motion)
        self.selector = selectors.DefaultSelector()
        self.token = secrets.token_hex(16)
        self.server = self._listen()
        self._restore_speed()

    # Live-event socket

    def _listen(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        server.setblocking(False)
        self.selector.register(server, selectors.EVENT_READ, None)
        config.SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.SOCKET_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"port": server.getsockname()[1], "token": self.token, "pid": os.getpid()}),
                       encoding="utf-8")
        tmp.replace(config.SOCKET_PATH)
        return server

    def _serve(self, timeout):
        for key, _ in self.selector.select(timeout):
            if key.fileobj is self.server:
                try:
                    conn, _ = self.server.accept()
                except OSError:
                    continue
                conn.setblocking(False)
                self.selector.register(conn, selectors.EVENT_READ, {"buffer": b"", "auth": False})
                continue
            conn, state = key.fileobj, key.data
            try:
                data = conn.recv(4096)
            except OSError:
                data = b""
            if not data:
                self._drop(conn)
                continue
            state["buffer"] += data
            while b"\n" in state["buffer"]:
                line, state["buffer"] = state["buffer"].split(b"\n", 1)
                self._command(conn, state, line.decode(errors="replace").strip())

    def _command(self, conn, state, line):
        if not state["auth"]:
            if not secrets.compare_digest(line, self.token):
                self._drop(conn)
                return
            state["auth"] = True
            with self.lock:
                self.clients.append(conn)
            self._send(conn, self._status())
        elif line == "quit":
            log.info("asked to quit")
            self.stopping.set()

    def _drop(self, conn):
        with self.lock:
            if conn in self.clients:
                self.clients.remove(conn)
        try:
            self.selector.unregister(conn)
        except (KeyError, ValueError):
            pass
        conn.close()

    def _send(self, conn, event):
        try:
            conn.send((json.dumps(event) + "\n").encode())
        except OSError:
            pass  # the select loop drops it

    def broadcast(self, event):
        kind = event.get("type")
        if (kind == "button" and event.get("pressed")) or kind == "scroll":
            for runner in list(self.effects.values()):
                if runner.key == event.get("device"):
                    runner.click(kind)
        with self.lock:
            clients = list(self.clients)
        for conn in clients:
            self._send(conn, event)

    def _status(self):
        return {"type": "status", "managed": sorted(self.managed)}

    # Mouse input (hook thread)

    def _managed_for(self, device):
        managed = self.managed.get(key_of_path(device)) if device else None
        if managed is None and device is None and len(self.managed) == 1:
            managed = next(iter(self.managed.values()))  # nothing moved yet: the only managed mouse
        return managed

    def on_mouse(self, message, data, device):
        events = winhook.mouse_event(message, data)
        if not events:
            return False
        with self.lock:
            managed = self._managed_for(device)
            if managed is None:
                return False
            for type_, code, value in events:
                managed.engine.handle(type_, code, value)
            produced = managed.out.take()
            self._precision()
        if produced == events:
            return False
        if produced:
            self.actions.run(winhook.inject, produced)
        return True

    def on_motion(self, device, dx, dy):
        with self.lock:
            managed = self.managed.get(key_of_path(device))
            if managed is None or not (managed.engine.hold or managed.engine.precision):
                return
            if dx:
                managed.engine.handle(e.EV_REL, e.REL_X, dx)
            if dy:
                managed.engine.handle(e.EV_REL, e.REL_Y, dy)
            # Motion itself always passes; only what a swipe triggers is injected.
            produced = [ev for ev in managed.out.take() if ev[0] == e.EV_KEY]
        if produced:
            self.actions.run(winhook.inject, produced)

    def _precision(self):
        held = [m for m in self.managed.values() if m.engine.precision]
        if held and self.base_speed is None:
            self.base_speed = winhook.mouse_speed()
            try:
                SPEED_PATH.write_text(str(self.base_speed), encoding="utf-8")
            except OSError:
                pass
            factor = held[0].engine.profile.get("precision", config.DEFAULT_PRECISION)
            winhook.set_mouse_speed(max(1, round(self.base_speed * factor)))
        elif not held and self.base_speed is not None:
            winhook.set_mouse_speed(self.base_speed)
            self.base_speed = None
            try:
                SPEED_PATH.unlink()
            except OSError:
                pass

    def _restore_speed(self):
        """Put back a pointer speed left lowered by a precision mode that never ended (a crash)."""
        try:
            speed = int(SPEED_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        winhook.set_mouse_speed(speed)
        SPEED_PATH.unlink(missing_ok=True)

    # The GM500W's programmed keys

    def _key_action(self, key, name):
        profile = self.config["devices"].get(key) or {}
        action = profile.get("buttons", {}).get(name, {}).get("click")
        return None if not action or action["type"] == "default" else action

    def _mapped_usage(self, usage):
        """Whether a managed GM500W gives the button sending `usage` an action."""
        name = USAGE_BUTTONS.get(usage)
        return bool(name) and any(self._key_action(key, name) for key in self.readers)

    def vendor_report(self, reader, report):
        """A report from a GM500W's input collections (reader threads)."""
        dpi = vendor.parse_input(report)
        if dpi:
            if dpi[0] == "dpi-press":
                for runner in list(self.effects.values()):
                    if runner.key == reader.key:
                        runner.click()
            return
        if len(report) < 3 or report[0] != vendor.KEY_REPORT:
            return
        usage = report[1] | report[2] << 8
        if usage:
            with self.lock:
                self.mouse_keys.append((usage, time.monotonic()))
                vk = USAGE_VKS.get(usage)
                if vk in self.pending:
                    self.pending[vk]["claimed"] = True
            name = USAGE_BUTTONS.get(usage)
            if not name:
                return
            action = self._key_action(reader.key, name)
            reader.pressed = (name, action)
            self.broadcast({"type": "button", "device": reader.key, "button": name, "pressed": True})
            if action:
                self._run_key_action(reader.key, action, True)
        elif reader.pressed:
            name, action = reader.pressed
            reader.pressed = None
            self.broadcast({"type": "button", "device": reader.key, "button": name, "pressed": False})
            if action:
                self._run_key_action(reader.key, action, False)

    def _run_key_action(self, key, action, pressed):
        kind = action["type"]
        if kind == "keys":
            (self.actions.press if pressed else self.actions.release)(action)
        elif kind == "button":
            self.actions.run(winhook.send_button, devices.BUTTON_CODES[action["button"]], pressed)
        elif pressed and kind not in ("disabled", "precision"):
            self.actions.tap(action)

    def on_key(self, vk, scan, down):
        """Hold back media keys a managed mouse button may have sent (hook thread)."""
        usage = VK_USAGES.get(vk)
        if usage is None or not self._mapped_usage(usage):
            return False
        now = time.monotonic()
        with self.lock:
            if down:
                if any(u == usage and now - t < KEY_HOLD for u, t in self.mouse_keys):
                    self.pending[vk] = {"claimed": True, "up": False}
                    return True
                if vk in self.pending:  # autorepeat of a key already held back
                    return True
                self.pending[vk] = {"claimed": False, "up": False}
                threading.Timer(KEY_HOLD, self._resolve_key, (vk,)).start()
                return True
            state = self.pending.get(vk)
            if state is None:
                return False
            if state["claimed"]:
                del self.pending[vk]
                return True
            state["up"] = True  # resolved by the timer
            return True

    def _resolve_key(self, vk):
        with self.lock:
            state = self.pending.get(vk)
            if state is None:
                return
            if state["claimed"]:
                if state["up"]:
                    del self.pending[vk]
                return
            del self.pending[vk]
            up = state["up"]
        # Not from the mouse: let the keyboard's key through after all.
        # A release still to come finds no pending entry and passes the hook unchanged.
        self.actions.run(winhook.send_vk, vk, True)
        if up:
            self.actions.run(winhook.send_vk, vk, False)

    # Devices and lighting

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
        with self.lock:
            for key, managed in self.managed.items():
                managed.engine.set_profile(self.config["devices"].get(key))
        log.info("config reloaded")
        return True

    def rescan(self):
        present = {}
        for info in devices.scan():
            profile = self.config["devices"].get(info.key)
            if profile and profile.get("enabled") and info.key not in present:
                present[info.key] = info
        changed = False
        with self.lock:
            for key in list(self.managed):
                if key not in present:
                    managed = self.managed.pop(key)
                    managed.engine.reset()
                    released = managed.out.take()
                    if released:
                        self.actions.run(winhook.inject, released)
                    log.info("released %s", key)
                    changed = True
            for key, info in present.items():
                if key in self.managed:
                    continue
                out = Output()
                engine = Engine(out, self.actions, self.broadcast, key)
                engine.set_profile(self.config["devices"].get(key))
                self.managed[key] = Managed(info, engine, out)
                log.info("managing %s (%s)", info.name, key)
                changed = True
            self._precision()
        if changed:
            self.broadcast(self._status())
        self.sync_readers()
        self.sync_lighting()

    def sync_readers(self):
        wanted = {}
        for key in list(self.managed):
            node = vendor.find_hidraw(key)
            if node:
                wanted[key] = node
        for key, reader in list(self.readers.items()):
            if wanted.get(key) != reader.node or reader.stopped.is_set():
                reader.stop()
                del self.readers[key]
        for key, node in wanted.items():
            if key in self.readers:
                continue
            try:
                reader = KeyReader(self, key, node)
            except OSError as err:
                log.warning("cannot read the keys of %s: %s", key, err)
                continue
            reader.start()
            self.readers[key] = reader
            log.info("reading keys of %s", key)

    def sync_lighting(self):
        """As on Linux (daemon.Daemon.sync_lighting): effects where chosen, saved lighting once per connection."""
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
                try:
                    runner.refresh()
                except OSError:
                    self._stop_effect(node)
                continue
            self._stop_effect(node)
            self.lit.discard(node)
            log.info("stopped effect on %s", runner.key)
        for node, (key, light) in present.items():
            if light.get("engine") == "mousekit":
                if node not in self.effects:
                    try:
                        self.effects[node] = EffectRunner(key, node, light, read_inputs=False)
                    except OSError as err:
                        log.warning("cannot start effect on %s: %s", key, err)
                        continue
                    log.info("effect %s on %s", light.get("effect"), key)
                continue
            if node in self.lit or "mode" not in light:
                continue
            try:
                apply_once(node, light)
            except OSError as err:
                log.warning("cannot restore lighting on %s: %s", key, err)
                continue
            self.lit.add(node)
            log.info("restored lighting on %s", key)
        self.lit &= set(present)

    def _stop_effect(self, node):
        runner = self.effects.pop(node)
        try:
            runner.stop()
        except OSError:
            pass

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
            return 0.5
        wait = min(runner.next_frame for runner in self.effects.values()) - time.monotonic()
        return max(0.0, min(0.5, wait))

    # Main loop

    def _work(self):
        """Everything but the hooks: devices, lighting, the socket."""
        try:
            self.rescan()
            last_scan = time.monotonic()
            while not self.stopping.is_set():
                self._serve(self.next_timeout())
                self.tick_effects()
                now = time.monotonic()
                if self.check_config() or now - last_scan >= SCAN_INTERVAL:
                    self.rescan()
                    last_scan = now
        except Exception:  # noqa: BLE001
            log.exception("service failed")
        finally:
            self.stopping.set()
            self.hooks.stop()

    def run(self):
        worker = threading.Thread(target=self._work, name="service", daemon=True)
        hooks_ready = threading.Thread(target=self._start_worker_when_ready, args=(worker,), daemon=True)
        hooks_ready.start()
        self.hooks.run()  # the hooks need this thread's message loop; returns once stopped
        self.stopping.set()
        worker.join(3)

    def _start_worker_when_ready(self, worker):
        try:
            self.hooks.wait_ready()
        except OSError as err:
            log.error("cannot install the input hooks: %s", err)
            self.hooks.stop()
            return
        worker.start()

    def shutdown(self):
        with self.lock:
            for key, managed in list(self.managed.items()):
                managed.engine.reset()
                winhook.inject(managed.out.take())
            self.managed.clear()
            self._precision()
        for reader in self.readers.values():
            reader.stop()
        for node in list(self.effects):
            self._stop_effect(node)
        self.actions.close()
        self.server.close()
        try:
            if json.loads(config.SOCKET_PATH.read_text(encoding="utf-8")).get("pid") == os.getpid():
                config.SOCKET_PATH.unlink()
        except (OSError, ValueError):
            pass


class UpdateWatcher(threading.Thread):
    """Checks GitHub for a newer release every hour and shows a notification once per version."""

    FIRST_CHECK = 120

    def __init__(self):
        super().__init__(name="updates", daemon=True)

    def run(self):
        wait = self.FIRST_CHECK
        while True:
            time.sleep(wait)
            wait = updates.CHECK_INTERVAL
            if not config.load().get("check_updates", True):
                continue
            try:
                newer = updates.newer_releases(updates.fetch_releases())
            except (OSError, ValueError) as err:
                log.info("update check failed: %s", err)
                continue
            if not newer or not updates.package_asset(newer[0]):
                continue
            version = updates.release_version(newer[0])
            if updates.last_notified() != version:
                log.info("update %s available", version)
                updates.set_notified(version)
                updates.notify_update(version)


def _single_instance():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def running():
    """Whether the service runs in this session."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    handle = kernel32.OpenMutexW(0x00100000, False, MUTEX_NAME)  # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return True
    return False


def main():
    config.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(config.LOCAL_DIR / "service.log", maxBytes=512 * 1024,
                                                     backupCount=1, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=handlers)
    mutex = _single_instance()
    if mutex is None:
        log.info("the service is already running")
        return
    log.info("Mousekit service %s starting", updates.__version__)
    if updates.installed_from_package():
        UpdateWatcher().start()
    service = Service()
    try:
        service.run()
    except KeyboardInterrupt:
        pass
    finally:
        service.shutdown()
        log.info("stopped")
