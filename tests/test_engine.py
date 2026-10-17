import unittest

from evdev import ecodes as e

from mousekit.engine import Engine, detect_swipe
from mousekit import effects
from mousekit.keys import parse_combo
from mousekit.vendor import DPI_STEPS, media_record, dpi_blocks, dpi_config, is_key_press, stored_lighting_blocks, lighting, lighting_packets, mode_packet, parse_input, slot_packets

LEFT_DESKTOP = {"type": "shortcut", "component": "kwin", "name": "Switch One Desktop to the Left"}
RIGHT_DESKTOP = {"type": "shortcut", "component": "kwin", "name": "Switch One Desktop to the Right"}
VOLUME_UP = {"type": "shortcut", "component": "kmix", "name": "increase_volume"}


class FakeOut:
    def __init__(self):
        self.events = []

    def write(self, type_, code, value):
        self.events.append((type_, code, value))

    def syn(self):
        self.events.append("syn")

    def keys(self):
        return [ev for ev in self.events if ev != "syn" and ev[0] == e.EV_KEY]

    def motion(self):
        return [ev for ev in self.events if ev != "syn" and ev[0] == e.EV_REL]


class FakeActions:
    def __init__(self):
        self.calls = []

    def tap(self, action):
        self.calls.append(("tap", action))

    def press(self, action):
        self.calls.append(("press", action))

    def release(self, action):
        self.calls.append(("release", action))


def make(buttons, **profile):
    out, actions = FakeOut(), FakeActions()
    engine = Engine(out, actions)
    engine.set_profile({"buttons": buttons, "gesture": {"threshold": 50, "hold_ms": 160}, **profile})
    return engine, out, actions


GESTURE_MIDDLE = {"BTN_MIDDLE": {"swipe": {"left": RIGHT_DESKTOP, "right": LEFT_DESKTOP}}}


class DetectSwipeTest(unittest.TestCase):
    # The cases OpenLogi's own tests pin down for swipe.rs.
    def test_openlogi_cases(self):
        cases = [((40, 5), None), ((120, 5), "right"), ((-120, 5), "left"), ((5, 120), "down"),
                 ((5, -120), "up"), ((60, 60), None), ((50, 0), "right"), ((49, 0), None),
                 ((200, 69), "right"), ((200, 71), None), ((100, 39), "right"), ((100, 41), None)]
        for (dx, dy), expected in cases:
            self.assertEqual(detect_swipe(dx, dy, 50), expected, (dx, dy))


class GestureTest(unittest.TestCase):
    def test_swipe_fires_once_and_swallows_click(self):
        engine, out, actions = make(GESTURE_MIDDLE)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 1, now=0.0)
        engine.handle(e.EV_REL, e.REL_X, -30, now=0.2)
        engine.handle(e.EV_REL, e.REL_X, -30, now=0.25)
        engine.handle(e.EV_REL, e.REL_X, -100, now=0.3)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 0, now=0.4)
        self.assertEqual(actions.calls, [("tap", RIGHT_DESKTOP)])
        self.assertEqual(out.keys(), [])
        # The cursor kept moving during the hold.
        self.assertEqual(sum(v for _, _, v in out.motion()), -160)

    def test_quick_press_is_a_click_even_if_the_cursor_drifted(self):
        engine, out, actions = make(GESTURE_MIDDLE)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 1, now=0.0)
        engine.handle(e.EV_REL, e.REL_X, -200, now=0.05)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 0, now=0.1)
        self.assertEqual(actions.calls, [])
        self.assertEqual(out.keys(), [(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_KEY, e.BTN_MIDDLE, 0)])

    def test_unbound_direction_still_clicks(self):
        engine, out, actions = make(GESTURE_MIDDLE)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 1, now=0.0)
        engine.handle(e.EV_REL, e.REL_Y, -300, now=0.3)
        engine.handle(e.EV_KEY, e.BTN_MIDDLE, 0, now=0.5)
        self.assertEqual(actions.calls, [])
        self.assertEqual(out.keys(), [(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_KEY, e.BTN_MIDDLE, 0)])

    def test_wheel_while_held(self):
        engine, out, actions = make({"BTN_EXTRA": {"wheel": {"up": VOLUME_UP}}})
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 1, now=0.0)
        engine.handle(e.EV_REL, e.REL_WHEEL, 2, now=0.1)
        engine.handle(e.EV_REL, e.REL_WHEEL_HI_RES, 240, now=0.1)
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 0, now=0.2)
        self.assertEqual(actions.calls, [("tap", VOLUME_UP), ("tap", VOLUME_UP)])
        self.assertEqual(out.events, [])  # wheel and click both swallowed

    def test_wheel_passes_through_without_hold(self):
        engine, out, _ = make({"BTN_EXTRA": {"wheel": {"up": VOLUME_UP}}})
        events = []
        engine.notify = events.append
        engine.handle(e.EV_REL, e.REL_WHEEL, 1)
        engine.handle(e.EV_REL, e.REL_WHEEL_HI_RES, 120)
        self.assertEqual(out.events, [(e.EV_REL, e.REL_WHEEL, 1), (e.EV_REL, e.REL_WHEEL_HI_RES, 120)])
        self.assertEqual([ev["type"] for ev in events], ["scroll"])  # one per notch, for the click flash


class RemapTest(unittest.TestCase):
    def test_default_buttons_pass_through(self):
        engine, out, _ = make({})
        for code in (e.BTN_LEFT, e.BTN_SIDE, e.BTN_MIDDLE):
            engine.handle(e.EV_KEY, code, 1)
            engine.handle(e.EV_KEY, code, 0)
        self.assertEqual(len(out.keys()), 6)

    def test_left_button_cannot_be_remapped(self):
        engine, out, _ = make({"BTN_LEFT": {"click": {"type": "disabled"}}})
        engine.handle(e.EV_KEY, e.BTN_LEFT, 1)
        self.assertEqual(out.keys(), [(e.EV_KEY, e.BTN_LEFT, 1)])

    def test_button_remap_keeps_drag(self):
        engine, out, _ = make({"BTN_EXTRA": {"click": {"type": "button", "button": "BTN_MIDDLE"}}})
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 1)
        engine.handle(e.EV_REL, e.REL_X, 10)
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 0)
        self.assertEqual(out.events, [(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_REL, e.REL_X, 10),
                                      (e.EV_KEY, e.BTN_MIDDLE, 0)])

    def test_keys_follow_the_button(self):
        combo = {"type": "keys", "combo": "Ctrl+C"}
        engine, _, actions = make({"BTN_SIDE": {"click": combo}})
        engine.handle(e.EV_KEY, e.BTN_SIDE, 1)
        engine.handle(e.EV_KEY, e.BTN_SIDE, 0)
        self.assertEqual(actions.calls, [("press", combo), ("release", combo)])

    def test_shortcut_fires_on_press_only(self):
        engine, _, actions = make({"BTN_EXTRA": {"click": VOLUME_UP}})
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 1)
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 0)
        self.assertEqual(actions.calls, [("tap", VOLUME_UP)])

    def test_release_uses_the_action_from_press_time(self):
        engine, out, _ = make({"BTN_EXTRA": {"click": {"type": "button", "button": "BTN_MIDDLE"}}})
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 1)
        engine.set_profile({"buttons": {}})
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 0)
        self.assertEqual(out.keys(), [(e.EV_KEY, e.BTN_MIDDLE, 1), (e.EV_KEY, e.BTN_MIDDLE, 0)])

    def test_reset_releases_held_buttons(self):
        engine, out, _ = make({})
        engine.handle(e.EV_KEY, e.BTN_SIDE, 1)
        engine.reset()
        self.assertEqual(out.keys(), [(e.EV_KEY, e.BTN_SIDE, 1), (e.EV_KEY, e.BTN_SIDE, 0)])


class PrecisionTest(unittest.TestCase):
    def test_motion_is_scaled_without_losing_remainders(self):
        engine, out, _ = make({"BTN_EXTRA": {"click": {"type": "precision"}}}, precision=0.25)
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 1)
        for _ in range(8):
            engine.handle(e.EV_REL, e.REL_X, 1)
        engine.handle(e.EV_KEY, e.BTN_EXTRA, 0)
        engine.handle(e.EV_REL, e.REL_X, 4)
        self.assertEqual(sum(v for _, _, v in out.motion()), 2 + 4)


class VendorTest(unittest.TestCase):
    # Reports recorded from a GM500W while cycling DPI up and down.
    def test_dpi_reports(self):
        self.assertEqual(parse_input(bytes.fromhex("06f801")), ("dpi-press", "up", 1))
        self.assertEqual(parse_input(bytes.fromhex("06f882")), ("dpi-set", "up", 2))
        self.assertEqual(parse_input(bytes.fromhex("06f680")), ("dpi-set", "down", 0))
        self.assertIsNone(parse_input(bytes.fromhex("0300000000")))

    def test_programmed_keys(self):
        # Recorded: Fire = Play/Pause (02 cd 00), Forward = Next track (02 b5 00), then release (02 00 00).
        self.assertTrue(is_key_press(bytes.fromhex("02cd00")))
        self.assertTrue(is_key_press(bytes.fromhex("02b500")))
        self.assertFalse(is_key_press(bytes.fromhex("020000")))
        self.assertFalse(is_key_press(bytes.fromhex("06f882")))

    def test_lighting_mode(self):
        # Factory Ambilight (mode 7, speed 3), static colour (2), LEDs off (13), as read from the mouse.
        self.assertEqual(lighting(bytes.fromhex("07007a09320003797301")), (7, 3))
        self.assertEqual(lighting(bytes.fromhex("07007a09320003292001")), (2, 0))
        self.assertEqual(lighting(bytes.fromhex("07007c095a0003d9d304")), (13, 3))

    def test_packets(self):
        # Packets checked on the mouse: static green, LEDs off, mono water from palette slot 0.
        self.assertEqual(mode_packet(2, 0, 4, 1, False, 0), [0x07, 0x13, 0x80, 0xA0, 0x19, 0x04, 0x00, 0x02])
        self.assertEqual(slot_packets((0, 255, 0))[1], [0x07, 0x14, 0x20, 0xFF, 0, 0, 0, 0])
        self.assertEqual(mode_packet(13, 3, 4, 0, False, 0), [0x07, 0x13, 0x80, 0xD3, 0x09, 0x04, 0x80, 0x02])
        mono = lighting_packets({"mode": 4, "speed": 2, "bright": 7, "color": (0, 255, 0)})
        self.assertEqual(mono, [[0x07, 0x14, 0x10, 0xFF, 0, 0, 0, 0], [0x07, 0x13, 0x81, 0xC2, 0x09, 0x00, 0x00, 0x02]])

    def test_media_record(self):
        # The vendor app's records for Forward (next track) and Fire (play/pause), read from the mouse.
        self.assertEqual(media_record(0xB5), bytes.fromhex("0000ffb5000004000000"))
        self.assertEqual(media_record(0xCD), bytes.fromhex("0000ffcd000004000000"))

    def test_dpi_registers(self):
        block10 = bytes.fromhex("f500003008" "6cdf12")     # dumped: codes 6, 12, 13, 15, 17, 18
        block18 = bytes.fromhex("193f0800f3ff0000")
        stages, current = dpi_config(block10, block18)
        self.assertEqual(stages, [(1200, True), (2400, True), (3200, True), (4800, True), (6400, True), (7200, True)])
        self.assertEqual(current, 1)
        # Writing the same stages back changes nothing.
        self.assertEqual(dpi_blocks(block10, block18, stages), (block10, block18))
        new10, new18 = dpi_blocks(block10, block18, [(800, True), (1600, True), (2400, False),
                                                     (12800, True), (200, True), (2000, False)])
        self.assertEqual(dpi_config(new10, new18)[0][3], (12800, True))
        self.assertEqual(new18[1], 0b011011)
        self.assertEqual(len(DPI_STEPS), 23)
        # The current stage is moved off a stage that gets switched off.
        _, moved = dpi_blocks(block10, block18, [(1200, True), (2400, False)] + stages[2:])
        self.assertEqual(moved[0] & 7, 0)

    def test_stored_lighting(self):
        # Registers 0x18-0x1f and 0x20-0x3f as dumped from the mouse (factory ambilight).
        block = bytes.fromhex("193f0800f3ff0000")
        colours = bytes.fromhex("001fffff8f0000ff80ff00bf00ffffff" "0000ff3f000000000000090000008f00")
        # Neon, speed 3: the one byte verified by saving and replugging.
        neon_block, neon_colours = stored_lighting_blocks(block, colours, {"mode": 6, "speed": 3, "bright": 7})
        self.assertEqual(neon_block, bytes.fromhex("193f0800e3ff0000"))
        self.assertEqual(neon_colours, colours)
        # Static purple: every DPI stage colour (low nibbles, inverted) changes, palette nibbles stay.
        _, purple = stored_lighting_blocks(block, colours, {"mode": 2, "color": (255, 0, 255), "bright": 7})
        self.assertEqual([c & 0x0F for c in purple[:18]], [0x0, 0xF, 0x0] * 6)
        self.assertEqual([c >> 4 for c in purple[:18]], [c >> 4 for c in colours[:18]])
        off_block, _ = stored_lighting_blocks(block, colours, {"mode": 13})
        self.assertEqual(off_block[4] & 0x07, 7)
        with self.assertRaises(ValueError):
            stored_lighting_blocks(block, colours, {"mode": 10})

    def test_lighting_settings(self):
        neon = lighting_packets({"mode": 6, "speed": 5, "bright": 1})
        self.assertEqual(len(neon), 8)                      # palette + mode
        self.assertEqual(neon[-1][2:6], [0xFF, 0xE5, 0x09, 0x06])
        self.assertEqual(lighting_packets({"mode": 13})[-1][2], 0x80)


class EffectsTest(unittest.TestCase):
    def test_every_effect_stays_in_range(self):
        for effect in effects.EFFECTS:
            for t in (0.0, 0.7, 3.1):
                rgb = effects.colour({"effect": effect, "color": (255, 0, 0)}, t, [0.5])
                self.assertTrue(all(0 <= c <= 255.001 for c in rgb), (effect, rgb))

    def test_click_flash_fades(self):
        light = {"effect": "click", "color": (0, 255, 0)}
        bright = effects.colour(light, 10.0, [10.0])[1]
        fading = effects.colour(light, 10.3, [10.0])[1]
        idle = effects.colour(light, 12.0, [10.0])[1]
        self.assertGreater(bright, fading)
        self.assertGreater(fading, idle)
        # Between clicks it glows at the background level, in the same colour.
        self.assertAlmostEqual(idle, 255 * 0.3)
        self.assertEqual(effects.colour({**light, "glow": 0}, 12.0, [10.0]), (0, 0, 0))

    def test_brightness_scales(self):
        full = effects.colour({"effect": "rainbow", "bright": 7}, 0)
        dim = effects.colour({"effect": "rainbow", "bright": 1}, 0)
        self.assertAlmostEqual(max(dim) * 7, max(full), places=3)


class KeysTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_combo("Meta+Ctrl+Left"), [e.KEY_LEFTMETA, e.KEY_LEFTCTRL, e.KEY_LEFT])
        self.assertEqual(parse_combo("Ctrl++"), [e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_EQUAL])
        self.assertEqual(parse_combo("F13"), [e.KEY_F13])
        self.assertEqual(parse_combo("Media Next"), [e.KEY_NEXTSONG])
        with self.assertRaises(ValueError):
            parse_combo("Ctrl+")
        with self.assertRaises(ValueError):
            parse_combo("Hyper+X")


if __name__ == "__main__":
    unittest.main()
