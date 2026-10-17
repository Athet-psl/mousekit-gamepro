"""Everything needed to add support for a new mouse, as text for a GitHub issue.

    mousekit --dump [vvvv:pppp] [--record SECONDS] [-o FILE]

Collects the USB interfaces and HID report descriptors from sysfs and, while
the user presses each button, records the raw reports the mouse sends.
Read-only: nothing is ever sent to the mouse. Raw reports come from
/dev/hidraw*, which usually needs root for a mouse Mousekit doesn't know yet.
"""

import argparse
import os
import platform
import selectors
import sys
import time
from pathlib import Path

from . import __version__, devices, models, updates, usbinfo

RECORD_SECONDS = 15
MAX_RECORD_LINES = 600
RECORD_HINT = ("Press each button once, slowly, one after another (also DPI, lighting and any others), "
               "then turn the wheel one notch up and one down. Don't move the mouse.")


def _hex(data, indent="    ", width=16):
    return "\n".join(indent + data[i:i + width].hex(" ") for i in range(0, len(data), width))


def _event_caps(event):
    from evdev import ecodes as e
    parts = []
    for kind, names in (("key", e.KEY | e.BTN), ("rel", e.REL), ("abs", e.ABS), ("msc", e.MSC)):
        words = event[kind].split()
        bits = []
        for index, word in enumerate(reversed(words)):
            value = int(word, 16)
            while value:
                low = value & -value
                bits.append(index * 64 + low.bit_length() - 1)
                value ^= low
        if len(bits) > 24:  # a keyboard interface: the descriptor already says which
            parts.append(f"{kind}: {len(bits)} codes")
        elif bits:
            labels = []
            for code in sorted(bits):
                name = names.get(code, f"0x{code:x}")
                labels.append(name[0] if isinstance(name, (list, tuple)) else name)
            parts.append(f"{kind}: " + " ".join(labels))
    return parts


def collect(key):
    """The descriptor part of the dump for mouse "vvvv:pppp"."""
    usbs = usbinfo.usb_devices(key)
    if not usbs:
        raise LookupError(f"no USB device {key} is connected")
    usb = usbs[0]
    read = lambda name: usbinfo._read(usb / name)
    model = models.identify(key)
    lines = [
        f"Mousekit dump: {key}",
        f"Mousekit {__version__}, Linux {platform.release()}",
        f"Known model: {model['name'] if model else 'no'}",
        f"Fingerprint: {usbinfo.fingerprint(usb)}",
        "",
        f"USB: {read('manufacturer')} / {read('product')}",
        f"  bcdDevice {read('bcdDevice')}, USB {read('version')}, {read('speed')} Mb/s, {read('bMaxPower')}",
    ]
    for iface in usbinfo.interfaces(usb):
        lines += ["", f"Interface {iface['number']}: class {iface['class']}"]
        for ep in iface["endpoints"]:
            lines.append(f"  endpoint {ep['address']}: {ep['type'].lower()}, {ep['size']} bytes, interval {ep['interval']}")
        for hid in iface["hids"]:
            nodes = ", ".join(hid["hidraw"]) or "no hidraw"
            lines.append(f"  HID ({nodes}), report descriptor {len(hid['descriptor'])} bytes:")
            lines += ["  " + line for line in usbinfo.describe_report_descriptor(hid["descriptor"])]
            lines.append(_hex(hid["descriptor"]))
            for event in hid["events"]:
                lines.append(f"  input {event['node']}: \"{event['name']}\"")
                lines += ["    " + part for part in _event_caps(event)]
    return "\n".join(lines)


def _nodes(key):
    hidraw, events = [], []
    for usb in usbinfo.usb_devices(key)[:1]:
        for iface in usbinfo.interfaces(usb):
            for hid in iface["hids"]:
                hidraw += [f"/dev/{name}" for name in hid["hidraw"]]
                events += [f"/dev/input/{ev['node']}" for ev in hid["events"]]
    return hidraw, events


def can_record_raw(key):
    hidraw, _ = _nodes(key)
    return bool(hidraw) and all(os.access(node, os.R_OK) for node in hidraw)


def record(key, seconds, out=print):
    """Print what the mouse sends for `seconds`: raw HID reports and the input events Linux makes of them."""
    import evdev
    from evdev import ecodes as e
    hidraw, events = _nodes(key)
    selector = selectors.DefaultSelector()
    skipped = []
    for node in hidraw:
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            skipped.append(node)
            continue
        selector.register(fd, selectors.EVENT_READ, ("raw", Path(node).name))
    for node in events:
        try:
            dev = evdev.InputDevice(node)
        except OSError:
            skipped.append(node)
            continue
        selector.register(dev, selectors.EVENT_READ, ("event", Path(node).name))
    out(f"Recording {seconds} s." + (f" Not readable (run as root to include): {', '.join(skipped)}." if skipped else ""))
    start = time.monotonic()
    count = 0
    try:
        while (left := start + seconds - time.monotonic()) > 0 and count < MAX_RECORD_LINES:
            for item, _ in selector.select(left):
                kind, name = item.data
                stamp = f"+{time.monotonic() - start:6.3f}  {name:9}"
                if kind == "raw":
                    try:
                        data = os.read(item.fileobj, 64)
                    except OSError:
                        continue
                    out(f"{stamp} {data.hex(' ')}")
                    count += 1
                    continue
                try:
                    batch = list(item.fileobj.read())
                except (BlockingIOError, OSError):
                    continue
                for ev in batch:
                    if ev.type == e.EV_SYN or (ev.type == e.EV_REL and ev.code in (e.REL_X, e.REL_Y)):
                        continue
                    names = e.bytype.get(ev.type, {}).get(ev.code, ev.code)
                    label = names[0] if isinstance(names, (list, tuple)) else names
                    out(f"{stamp} {e.EV.get(ev.type, ev.type)} {label} {ev.value}")
                    count += 1
    finally:
        for item in list(selector.get_map().values()):
            if item.data[0] == "raw":
                os.close(item.fileobj)
            else:
                item.fileobj.close()
        selector.close()
    if count >= MAX_RECORD_LINES:
        out(f"(stopped after {MAX_RECORD_LINES} lines: was the mouse moving?)")
    elif not count:
        out("(nothing recorded)")


def _choose():
    mice = devices.scan()
    if not mice:
        sys.exit("No mouse found.")
    if len(mice) == 1:
        return mice[0].key
    for index, mouse in enumerate(mice, 1):
        print(f"  {index}. {models.display_name(mouse.key, mouse.name)} ({mouse.key})")
    while True:
        answer = input("Which mouse? ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(mice):
            return mice[int(answer) - 1].key


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mousekit --dump", description=__doc__.split("\n\n")[0])
    parser.add_argument("key", nargs="?", help="USB id of the mouse, like 30fa:1440 (asks if there are several)")
    parser.add_argument("--record", type=int, metavar="SECONDS", help="record button presses without asking")
    parser.add_argument("--recording-only", action="store_true", help="print only the recording (used by the app)")
    parser.add_argument("-o", "--output", help="file to write (default: mousekit-dump-vvvv-pppp.txt here)")
    args = parser.parse_args(argv)
    key = (args.key or _choose()).lower()

    if args.recording_only:
        record(key, args.record or RECORD_SECONDS, out=lambda line: print(line, flush=True))
        return
    try:
        text = collect(key)
    except LookupError as err:
        sys.exit(str(err))
    lines = []
    seconds = args.record
    if seconds is None and sys.stdin.isatty():
        if not can_record_raw(key):
            print("Note: raw reports need root for this mouse: run with sudo to include them.")
        answer = input(f"Record button presses for {RECORD_SECONDS} s now? [Y/n] ").strip().lower()
        seconds = RECORD_SECONDS if answer in ("", "y", "yes") else 0
    if seconds:
        print(RECORD_HINT)
        input("Press Enter to start.") if sys.stdin.isatty() else None
        record(key, seconds, out=lambda line: (lines.append(line), print(line, flush=True)))
        text += "\n\nRecording. " + RECORD_HINT + "\n" + "\n".join(lines)
    output = Path(args.output or f"mousekit-dump-{key.replace(':', '-')}.txt")
    output.write_text(text + "\n")
    print(f"\nWrote {output.resolve()}")
    print(f"Attach it to an issue: {updates.new_mouse_issue()}")
