"""The vendor HID channel of Instant Microelectronics (USB 30fa) mice: status, DPI events, live lighting.

Observed on a GamePro GM500W (30fa:1440):
- GET_FEATURE report 0x07 on the vendor interface returns a 32-byte status
  block; byte 8 is the lighting mode and speed.
- Register 0x18 (read the vendor app's way, see read_register) holds the
  current DPI stage in byte 0 and the enabled-stage mask in byte 1.
- Every press of DPI+ / DPI- sends input report 0x06: [06, f8|f6, stage]
  on press and [06, f8|f6, 0x80 | new_stage] once the firmware applied it.
  f8 is DPI+, f6 is DPI-. Stages clamp at the ends instead of wrapping.
Lighting writes (07 13 mode, 07 14 zone colour) are live only: nothing is
committed to the mouse's memory, so a replug restores its stored lighting.
See docs/GM500W-PROTOCOL.md.
"""

import fcntl
import os
import time
from pathlib import Path

VENDOR_ID = 0x30FA
STATUS_REPORT = 0x07
STATUS_SIZE = 32
DPI_REGISTER = 0x18
DPI_REPORT = 0x06
DPI_BUTTONS = {0xF8: "up", 0xF6: "down"}
DPI_STAGES = {"30fa:1440": 6}  # stage count isn't in the status block; observed per model

# Vendor usage page 0xFF01 declaring feature report 0x07.
_CONFIG_PAGE = bytes([0x06, 0x01, 0xFF])
_CONFIG_REPORT = bytes([0x85, STATUS_REPORT])


def _hidiocgfeature(size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | 0x07


def find_hidraw(key):
    """The /dev/hidrawN carrying the vendor config channel of mouse "vvvv:pppp", if accessible."""
    vendor, product = (int(part, 16) for part in key.split(":"))
    if vendor != VENDOR_ID:
        return None
    wanted = f"{vendor:04X}:{product:04X}"
    for entry in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        device = entry.resolve() / "device"
        if wanted not in device.resolve().name:
            continue
        try:
            descriptor = (device / "report_descriptor").read_bytes()
        except OSError:
            continue
        node = f"/dev/{entry.name}"
        if _CONFIG_PAGE in descriptor and _CONFIG_REPORT in descriptor and os.access(node, os.R_OK | os.W_OK):
            return node
    return None


def read_status(fd):
    buf = bytearray(STATUS_SIZE)
    buf[0] = STATUS_REPORT
    size = fcntl.ioctl(fd, _hidiocgfeature(STATUS_SIZE), buf, True)
    return bytes(buf[:size])


LED_BYTE = 8  # (mode << 4) | speed of the mode the mouse is showing
LED_COUNT = 9  # low nibble of mode byte 4 in the GM500 build of the vendor app
SINGLE_COLOUR_MODES = {2, 4}  # the modes that take a user colour


def lighting(status):
    """(mode, speed) of the onboard lighting, or None."""
    if len(status) <= LED_BYTE:
        return None
    return status[LED_BYTE] >> 4, status[LED_BYTE] & 0x0F


def _hidiocsfeature(size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | 0x06


def send(fd, packet, delay=0.002):
    fcntl.ioctl(fd, _hidiocsfeature(len(packet)), bytes(packet))
    time.sleep(delay)  # the vendor app waits 2 ms between reports


def _register_packet(flags, index, address, length):
    # 07 18 flags index addrL addrH data length-1 (vendor app fn 0x4138e0)
    return [0x07, 0x18, flags, index, address & 0xFF, address >> 8, 0x00, length - 1]


def read_register(fd, address, length):
    """Read device registers exactly like the vendor app (fn 0x413a90).

    Request every byte (flags 03), go idle, then for each byte ask for it
    (flags 05) and collect it from byte 1 of the next GET_FEATURE.
    """
    for i in range(length):
        send(fd, _register_packet(0x03, i, address, length))
    send(fd, [0x07, 0x18, 0x00, 0x00, address & 0xFF, address >> 8, 0x00, 0x00])
    data = []
    for i in range(length):
        send(fd, _register_packet(0x05, i, address, length))
        data.append(read_status(fd)[1])
    send(fd, [0x07, 0x18, 0, 0, 0, 0, 0, 0])
    return bytes(data)


def write_register(fd, address, data):
    """Write device registers exactly like the vendor app (fn 0x4139e0).

    Stage every byte (flags 03, byte value in b6), wait 4 ms, store the
    staged bytes to the register (flags 09), wait 2 ms, go idle. Like the
    live commands this only changes the running config; commit() saves it.
    """
    length = len(data)
    for i, value in enumerate(data):
        packet = _register_packet(0x03, i, address, length)
        packet[6] = value
        send(fd, packet, delay=0)
    time.sleep(0.004)
    send(fd, [0x07, 0x18, 0x09, 0x00, address & 0xFF, address >> 8, 0x00, length - 1])
    send(fd, [0x07, 0x18, 0x00, 0x00, address & 0xFF, address >> 8, 0x00, 0x00])


def commit(fd):
    """Save the running config to the mouse's memory (vendor app fn 0x413d30)."""
    send(fd, [0x07, 0x18, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00], delay=0.005)
    send(fd, [0x07, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


# Stored config (what the mouse loads at power-up), from the vendor app's save routine (fn 0x41a410):
#   0x1c  lighting mode byte: 0x80 | (mode & 7) << 4 | speed (speed 7 = LEDs off)
#   0x1d  0x80 | palette mask
#   0x20-0x31  6 DPI stages x (R, G, B): low nibble = stage colour, high nibble = palette slot (inverted)
#   0x3a  symmetry << 6 | direction << 4 | LED count
#   0x3f  bits 4-6: brightness byte (0 = brightest)
STORED_BLOCK = 0x18
COLOUR_BLOCK = 0x20
SAVABLE_MODES = set(range(8)) | {13}  # how the app stores modes 8-12 is not understood yet


def stored_lighting_blocks(block, colours, light):
    """The two stored blocks with light applied; block = regs 0x18-0x1f, colours = 0x20-0x3f."""
    block, colours = bytearray(block), bytearray(colours)
    mode = light["mode"]
    if mode not in SAVABLE_MODES:
        raise ValueError(f"saving mode {mode} to the mouse isn't supported")
    speed = max(0, min(5, light.get("speed", 3)))
    if mode == 13:  # the app stores "off" as speed 7
        mode, speed = 2, 7
    block[4] = 0x80 | (mode << 4) | speed
    block[5] = 0x80 | (0x00 if mode in (2,) or speed == 7 else 0x01 if mode == 4 else 0x7F)
    level = 7 - max(1, min(7, light.get("bright", 7)))
    colours[0x1A] = (int(bool(light.get("symmetric"))) << 6) | ((light.get("direction", 0) & 3) << 4) | LED_COUNT
    colours[0x1F] = (colours[0x1F] & 0x0F) | ((level << 4) & 0x70)
    rgb = _nibbles(light.get("color") or (255, 255, 255))
    if mode == 2:                       # static shows the DPI stage colours: set every stage
        for stage in range(6):
            for channel in range(3):
                i = stage * 3 + channel
                colours[i] = (colours[i] & 0xF0) | rgb[channel]
    elif mode == 4:                     # mono water draws from palette slot 0
        for channel in range(3):
            colours[channel] = (colours[channel] & 0x0F) | (rgb[channel] << 4)
    return bytes(block), bytes(colours)


def save_lighting(fd, light):
    """Store a firmware lighting setting in the mouse's memory. Returns what was read back."""
    block = read_register(fd, STORED_BLOCK, 8)
    colours = read_register(fd, COLOUR_BLOCK, 32)
    new_block, new_colours = stored_lighting_blocks(block, colours, light)
    if new_block != block:
        write_register(fd, STORED_BLOCK, new_block)
    if new_colours != colours:
        write_register(fd, COLOUR_BLOCK, new_colours)
    if (read_register(fd, STORED_BLOCK, 8), read_register(fd, COLOUR_BLOCK, 32)) != (new_block, new_colours):
        raise OSError("the mouse didn't take the new settings; nothing was saved")
    commit(fd)
    return new_block, new_colours


# DPI: the app's 23 steps as device codes (0x0b is skipped) and their values, from its macro code (fn 0x418190).
DPI_VALUES = {code: 200 * code for code in range(1, 11)}
DPI_VALUES.update({0x0C: 2400, 0x0D: 3200})
DPI_VALUES.update({code: 3200 + 800 * (code - 0x0D) for code in range(0x0E, 0x18)})
DPI_VALUES[0x18] = 12800
DPI_STEPS = sorted(DPI_VALUES.values())
DPI_CODE = {value: code for code, value in DPI_VALUES.items()}
DPI_BLOCK = 0x10  # 0x13: bit 4 of each stage's code; 0x15-0x17: low nibbles, two stages per byte


def dpi_config(block10, block18):
    """[(dpi, enabled)] for the 6 stages and the current stage, from registers 0x10-0x17 and 0x18-0x1f."""
    high = block10[3]
    lows = [block10[5] >> 4, block10[5] & 0xF, block10[6] >> 4, block10[6] & 0xF, block10[7] >> 4, block10[7] & 0xF]
    stages = []
    for stage, low in enumerate(lows):
        code = ((high >> stage) & 1) << 4 | low
        stages.append((DPI_VALUES.get(code), bool(block18[1] >> stage & 1)))
    return stages, block18[0] & 0x07


def dpi_blocks(block10, block18, stages):
    """The two blocks with new stages [(dpi, enabled)] written in."""
    if not any(enabled for _, enabled in stages):
        raise ValueError("at least one DPI stage has to stay on")
    block10, block18 = bytearray(block10), bytearray(block18)
    codes = [DPI_CODE[dpi] for dpi, _ in stages]
    block10[3] = sum(((code >> 4) & 1) << stage for stage, code in enumerate(codes))
    for i in range(3):
        block10[5 + i] = (codes[2 * i] & 0xF) << 4 | (codes[2 * i + 1] & 0xF)
    block18[1] = (block18[1] & 0xC0) | sum(1 << stage for stage, (_, on) in enumerate(stages) if on)
    current = block18[0] & 0x07
    if not stages[current][1]:  # don't leave the mouse on a stage that's switched off
        current = next(stage for stage, (_, on) in enumerate(stages) if on)
        block18[0] = (block18[0] & 0xF8) | current
    return bytes(block10), bytes(block18)


def set_dpi_stage(fd, stage):
    """Make `stage` (0-based) the current DPI stage and save it."""
    block18 = bytearray(read_register(fd, STORED_BLOCK, 8))
    if not block18[1] >> stage & 1:
        raise ValueError("this DPI stage is switched off")
    block18[0] = (block18[0] & 0xF8) | stage
    write_register(fd, STORED_BLOCK, bytes(block18))
    if read_register(fd, STORED_BLOCK, 8) != bytes(block18):
        raise OSError("the mouse didn't take the new settings; nothing was saved")
    commit(fd)


def read_dpi_config(fd):
    return dpi_config(read_register(fd, DPI_BLOCK, 8), read_register(fd, STORED_BLOCK, 8))


def save_dpi(fd, stages):
    """Store DPI stages [(dpi, enabled)] in the mouse's memory, verified before committing."""
    block10 = read_register(fd, DPI_BLOCK, 8)
    block18 = read_register(fd, STORED_BLOCK, 8)
    new10, new18 = dpi_blocks(block10, block18, stages)
    if new10 != block10:
        write_register(fd, DPI_BLOCK, new10)
    if new18 != block18:
        write_register(fd, STORED_BLOCK, new18)
    if (read_register(fd, DPI_BLOCK, 8), read_register(fd, STORED_BLOCK, 8)) != (new10, new18):
        raise OSError("the mouse didn't take the new settings; nothing was saved")
    commit(fd)


# Hardware buttons: one code per slot at 0x08-0x10 (low 5 bits = function, bit 5 always set by the app) and a
# 10-byte action record per slot from 0xa0. Slot order is config.ini's KEYMAP.
BUTTON_TABLE = 0x08
SLOT_RECORDS = 0xA0
SLOTS = {"left": 1, "middle": 2, "right": 3, "back": 4, "forward": 5, "dpi_down": 6, "fire": 7, "dpi_up": 8, "led": 9}
MEDIA_CODE = 0x2F            # function 15: send the consumer key from the slot's record
FACTORY_CODES = {"dpi_down": 0x2C, "dpi_up": 0x2B}
# Consumer usages Mousekit gives the DPI buttons: Linux maps them to KEY_REWIND / KEY_FASTFORWARD.
DPI_KEY_USAGES = {"dpi_down": 0xB4, "dpi_up": 0xB3}


def media_record(usage):
    """A slot record that sends consumer usage `usage` (same layout as the vendor app's Forward/Fire records)."""
    return bytes([0x00, 0x00, 0xFF, usage & 0xFF, usage >> 8, 0x00, 0x04, 0x00, 0x00, 0x00])


def read_buttons(fd):
    """{slot name: (code, record)} from the stored button table."""
    codes = read_register(fd, BUTTON_TABLE, 8) + read_register(fd, BUTTON_TABLE + 8, 1)
    return {name: (codes[slot - 1], read_register(fd, SLOT_RECORDS + 10 * (slot - 1), 10))
            for name, slot in SLOTS.items()}


def dpi_buttons_remapped(buttons):
    return all(buttons[name] == (MEDIA_CODE, media_record(usage)) for name, usage in DPI_KEY_USAGES.items())


def set_dpi_buttons(fd, as_keys):
    """Make the DPI buttons send keys Mousekit can map (as_keys) or switch DPI again, and save it."""
    codes = bytearray(read_register(fd, BUTTON_TABLE, 8) + read_register(fd, BUTTON_TABLE + 8, 1))
    writes = []
    for name, usage in DPI_KEY_USAGES.items():
        slot = SLOTS[name]
        codes[slot - 1] = MEDIA_CODE if as_keys else FACTORY_CODES[name]
        writes.append((SLOT_RECORDS + 10 * (slot - 1), media_record(usage) if as_keys else bytes(10)))
    writes.append((BUTTON_TABLE, bytes(codes[:8])))
    for address, data in writes:
        if read_register(fd, address, len(data)) != data:
            write_register(fd, address, data)
    for address, data in writes:
        if read_register(fd, address, len(data)) != data:
            raise OSError("the mouse didn't take the new button settings; nothing was saved")
    commit(fd)  # the mouse reads its button table at power-up: takes effect after a replug


def read_dpi(fd):
    """(current stage, number of enabled stages) from register 0x18."""
    register = read_register(fd, DPI_REGISTER, 8)
    return register[0] & 0x07, bin(register[1]).count("1") or None


RAINBOW = [(255, 0, 0), (255, 136, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (136, 0, 255)]


def _nibbles(rgb):
    """4-bit channels, inverted (0 = full on)."""
    return tuple(15 - max(0, min(15, round(v / 17))) for v in rgb)


def slot_packet(slot, rgb):
    """07 14 for colour slot 0-7 (bit 4 clear): the DPI stages' colours.

    Static colour (mode 2) and DPI breathing (mode 0) show the slot of the
    current DPI stage, and the mouse flashes it when the stage changes.
    Verified: writing distinct slots lit the whole mouse in the current
    stage's colour, and DPI+ switched it to the next slot's.
    """
    r, g, b = _nibbles(rgb)
    return [0x07, 0x14, (slot << 5) | g, (r << 4) | b, 0, 0, 0, 0]


def slot_packets(rgb, slots=8):
    return [slot_packet(slot, rgb) for slot in range(slots)]


def stream_start_packet():
    """Static colour at full brightness: the canvas Mousekit's own effects paint on."""
    return mode_packet(2, 0, 0, 0, False, 0x00)


def palette_packets(colours):
    """07 14 with bit 4 set: the 7-slot colour palette the animated modes draw from."""
    packets = []
    for slot, rgb in enumerate(colours):
        r, g, b = _nibbles(rgb)
        packets.append([0x07, 0x14, (slot << 5) | 0x10 | g, (r << 4) | b, 0, 0, 0, 0])
    return packets


def mode_packet(mode, speed, level, direction, symmetric, mask):
    """07 13: level is the raw brightness byte (0 = brightest), mask the enabled palette slots."""
    # Bit 7 of byte 3 means "apply"; bit 3 of the mode goes in byte 6 (checked on the mouse).
    b3 = 0x80 | ((mode & 7) << 4) | (speed & 7)
    b4 = (int(bool(symmetric)) << 6) | ((direction & 3) << 4) | LED_COUNT
    return [0x07, 0x13, 0x80 | mask, b3, b4, level & 7, 0x80 if mode >= 8 else 0x00, 0x02]


def lighting_packets(light):
    """Packets for a setting {mode, speed 0-5, bright 1-7, direction, symmetric, color}."""
    mode = light["mode"]
    colour = light.get("color") or (255, 255, 255)
    if mode == 2:                       # static: the DPI stage slots, all one colour
        packets, mask = slot_packets(colour), 0x00
    elif mode == 4:                     # mono water: one palette slot (verified on the mouse)
        packets, mask = palette_packets([colour]), 0x01
    elif mode == 13:                    # LEDs off
        packets, mask = [], 0x00
    else:                               # the rest cycle through the whole palette
        packets, mask = palette_packets(RAINBOW), 0x7F
    level = 7 - max(1, min(7, light.get("bright", 7)))  # the app sends 7 - slider position
    speed = max(0, min(5, light.get("speed", 3)))       # the app's slider has 6 steps: 0-5
    return packets + [mode_packet(mode, speed, level, light.get("direction", 0), light.get("symmetric", False), mask)]


def apply_lighting(fd, light):
    """Send a lighting setting live (not committed to the mouse's memory)."""
    for packet in lighting_packets(light):
        send(fd, packet)


KEY_REPORT = 0x02  # consumer keys the mouse is programmed to send (e.g. 02 cd 00 = Play/Pause)


def is_key_press(report):
    """A media/consumer key press from a button programmed in the mouse (Fire, Forward...)."""
    return len(report) >= 2 and report[0] == KEY_REPORT and any(report[1:])


def parse_input(report):
    """("dpi-press", button, stage) or ("dpi-set", button, new_stage) for DPI reports, else None."""
    if len(report) < 3 or report[0] != DPI_REPORT or report[1] not in DPI_BUTTONS:
        return None
    button = DPI_BUTTONS[report[1]]
    if report[2] & 0x80:
        return "dpi-set", button, report[2] & 0x7F
    return "dpi-press", button, report[2]
