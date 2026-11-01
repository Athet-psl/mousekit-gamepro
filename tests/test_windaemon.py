"""The Windows service's decisions: which hooked events pass, which are swallowed and what is injected."""

import sys
import threading
import unittest
from collections import deque

if sys.platform != "win32":
    raise unittest.SkipTest("the Windows service needs Windows")

from mousekit import windaemon, winhook  # noqa: E402
from mousekit.codes import ecodes as e  # noqa: E402
from mousekit.devices import MouseInfo  # noqa: E402
from mousekit.engine import Engine  # noqa: E402

KEY = "30fa:1440"
DEVICE = r"\\?\hid#vid_30fa&pid_1440&mi_00#8&13d70af&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}"
OTHER = r"\\?\hid#vid_046d&pid_c077#7&1a2b3c&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}"
DESKTOP_RIGHT = {"type": "keys", "combo": "Ctrl+Meta+Right"}


class FakeActions:
    def __init__(self):
        self.calls = []

    def tap(self, action):
        self.calls.append(("tap", action))

    def press(self, action):
        self.calls.append(("press", action))

    def release(self, action):
        self.calls.append(("release", action))

    def run(self, func, *args):
        self.calls.append((func.__name__, args))


def service(buttons, **profile):
    svc = windaemon.Service.__new__(windaemon.Service)
    svc.lock = threading.RLock()
    svc.actions = FakeActions()
    svc.config = {"devices": {KEY: {"buttons": buttons, "gesture": {"threshold": 50, "hold_ms": 0}, **profile}}}
    svc.effects, svc.clients, svc.pending, svc.readers = {}, [], {}, {}
    svc.mouse_keys = deque(maxlen=16)
    svc.base_speed = None
    out = windaemon.Output()
    engine = Engine(out, svc.actions, lambda event: None, KEY)
    engine.set_profile(svc.config["devices"][KEY])
    svc.managed = {KEY: windaemon.Managed(MouseInfo(KEY, "test", DEVICE), engine, out)}
    return svc


def wheel(notches):
    return (notches * 120 & 0xFFFF) << 16


class MouseHookTest(unittest.TestCase):
    def test_unmapped_buttons_pass(self):
        svc = service({})
        self.assertFalse(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, DEVICE))
        self.assertFalse(svc.on_mouse(winhook.WM_MBUTTONUP, 0, DEVICE))
        self.assertFalse(svc.on_mouse(winhook.WM_LBUTTONDOWN, 0, DEVICE))
        self.assertEqual(svc.actions.calls, [])

    def test_wheel_passes(self):
        svc = service({})
        self.assertFalse(svc.on_mouse(winhook.WM_MOUSEWHEEL, wheel(1), DEVICE))
        self.assertFalse(svc.on_mouse(winhook.WM_MOUSEWHEEL, wheel(-1), DEVICE))

    def test_other_mice_are_left_alone(self):
        svc = service({"BTN_MIDDLE": {"click": {"type": "disabled"}}})
        self.assertFalse(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, OTHER))

    def test_remapped_button_is_swallowed_and_injected(self):
        svc = service({"BTN_MIDDLE": {"click": {"type": "button", "button": "BTN_SIDE"}}})
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, DEVICE))
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONUP, 0, DEVICE))
        self.assertEqual(svc.actions.calls, [("inject", ([(e.EV_KEY, e.BTN_SIDE, 1)],)),
                                             ("inject", ([(e.EV_KEY, e.BTN_SIDE, 0)],))])

    def test_side_button_to_keys(self):
        svc = service({"BTN_EXTRA": {"click": DESKTOP_RIGHT}})
        self.assertTrue(svc.on_mouse(winhook.WM_XBUTTONDOWN, winhook.XBUTTON2 << 16, DEVICE))
        self.assertTrue(svc.on_mouse(winhook.WM_XBUTTONUP, winhook.XBUTTON2 << 16, DEVICE))
        self.assertEqual(svc.actions.calls, [("press", DESKTOP_RIGHT), ("release", DESKTOP_RIGHT)])

    def test_disabled_button_is_swallowed(self):
        svc = service({"BTN_SIDE": {"click": {"type": "disabled"}}})
        self.assertTrue(svc.on_mouse(winhook.WM_XBUTTONDOWN, winhook.XBUTTON1 << 16, DEVICE))
        self.assertTrue(svc.on_mouse(winhook.WM_XBUTTONUP, winhook.XBUTTON1 << 16, DEVICE))
        self.assertEqual(svc.actions.calls, [])

    def test_swipe_fires_and_the_click_is_dropped(self):
        svc = service({"BTN_MIDDLE": {"swipe": {"right": DESKTOP_RIGHT}}})
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, DEVICE))
        svc.on_motion(DEVICE, 80, 3)
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONUP, 0, DEVICE))
        self.assertEqual(svc.actions.calls, [("tap", DESKTOP_RIGHT)])

    def test_held_button_without_swipe_clicks_on_release(self):
        svc = service({"BTN_MIDDLE": {"swipe": {"right": DESKTOP_RIGHT}}})
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, DEVICE))
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONUP, 0, DEVICE))
        self.assertEqual(svc.actions.calls, [("inject", ([(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_KEY, e.BTN_MIDDLE, 0)],))])

    def test_wheel_while_held_runs_the_action_instead_of_scrolling(self):
        svc = service({"BTN_MIDDLE": {"wheel": {"up": DESKTOP_RIGHT}}})
        svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, DEVICE)
        self.assertTrue(svc.on_mouse(winhook.WM_MOUSEWHEEL, wheel(1), DEVICE))
        self.assertEqual(svc.actions.calls, [("tap", DESKTOP_RIGHT)])

    def test_no_raw_input_yet_means_the_only_managed_mouse(self):
        svc = service({"BTN_MIDDLE": {"click": {"type": "disabled"}}})
        self.assertTrue(svc.on_mouse(winhook.WM_MBUTTONDOWN, 0, None))


class MediaKeyTest(unittest.TestCase):
    def setUp(self):
        self.svc = service({"FIRE": {"click": DESKTOP_RIGHT}})
        self.svc.readers = {KEY: object()}
        self.timers = []
        self.patch = unittest.mock.patch.object(threading, "Timer", self._timer)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def _timer(self, _delay, func, args):
        timer = unittest.mock.Mock()
        timer.start = lambda: self.timers.append((func, args))
        return timer

    def reader(self):
        reader = unittest.mock.Mock(key=KEY, pressed=None)
        return reader

    def test_key_from_the_mouse_is_dropped_and_mapped(self):
        reader = self.reader()
        self.assertTrue(self.svc.on_key(0xB3, 0, True))      # Windows' play/pause, before the HID report
        self.svc.vendor_report(reader, bytes([0x02, 0xCD, 0x00]))
        self.assertTrue(self.svc.on_key(0xB3, 0, False))
        self.svc.vendor_report(reader, bytes([0x02, 0x00, 0x00]))
        for func, args in self.timers:
            func(*args)
        self.assertEqual(self.svc.actions.calls, [("press", DESKTOP_RIGHT), ("release", DESKTOP_RIGHT)])

    def test_report_first_then_key(self):
        reader = self.reader()
        self.svc.vendor_report(reader, bytes([0x02, 0xCD, 0x00]))
        self.assertTrue(self.svc.on_key(0xB3, 0, True))
        self.assertTrue(self.svc.on_key(0xB3, 0, False))
        self.assertEqual(self.svc.pending, {})

    def test_keyboard_media_key_comes_through_late(self):
        self.assertTrue(self.svc.on_key(0xB3, 0, True))
        self.assertTrue(self.svc.on_key(0xB3, 0, False))
        for func, args in self.timers:
            func(*args)
        self.assertEqual(self.svc.actions.calls, [("send_vk", (0xB3, True)), ("send_vk", (0xB3, False))])

    def test_unmapped_buttons_leave_media_keys_alone(self):
        self.svc.config["devices"][KEY]["buttons"] = {}
        self.assertFalse(self.svc.on_key(0xB3, 0, True))

    def test_other_keys_pass(self):
        self.assertFalse(self.svc.on_key(0x41, 0, True))


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
