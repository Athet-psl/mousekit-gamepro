import sys
import unittest

from mousekit.codes import ecodes as e

if sys.platform != "linux":
    raise unittest.SkipTest("the Linux service needs evdev")

from mousekit import daemon  # noqa: E402


class FakeDevice:
    def __init__(self, held=()):
        self.held = list(held)
        self.grabbed = False

    def grab(self):
        self.grabbed = True

    def ungrab(self):
        self.grabbed = False

    def active_keys(self):
        return self.held


class GrabTest(unittest.TestCase):
    def test_grabs_a_released_device(self):
        dev = FakeDevice()
        daemon.grab_released(dev)
        self.assertTrue(dev.grabbed)

    def test_leaves_a_device_with_a_button_down(self):
        dev = FakeDevice(held=[e.BTN_LEFT])
        with self.assertRaises(daemon.Held):
            daemon.grab_released(dev)
        self.assertFalse(dev.grabbed)


if __name__ == "__main__":
    unittest.main()
