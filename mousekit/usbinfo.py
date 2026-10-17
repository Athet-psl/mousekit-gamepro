"""What a USB mouse looks like from sysfs: interfaces, HID report descriptors, input nodes.

Everything here is world-readable, so it needs no device access and sends
nothing to the mouse.
"""

import hashlib
from pathlib import Path

USB_DEVICES = Path("/sys/bus/usb/devices")

_MAIN = {0x8: "input", 0x9: "output", 0xB: "feature"}
_PAGES = {0x01: "Generic Desktop", 0x07: "Keyboard", 0x08: "LEDs", 0x09: "Button", 0x0C: "Consumer"}
_DESKTOP = {0x01: "Pointer", 0x02: "Mouse", 0x06: "Keyboard", 0x80: "System Control"}


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def usb_devices(key):
    """sysfs dirs of the connected USB devices with id "vvvv:pppp"."""
    return [d for d in sorted(USB_DEVICES.iterdir())
            if (d / "idVendor").exists() and f"{_read(d / 'idVendor')}:{_read(d / 'idProduct')}" == key]


def interfaces(usb):
    """Interfaces of a USB device dir, with their endpoints and HID functions."""
    found = []
    for iface in sorted(usb.glob(f"{usb.name}:*")):
        endpoints = [{
            "address": _read(ep / "bEndpointAddress"), "type": _read(ep / "type"),
            "size": int(_read(ep / "wMaxPacketSize") or "0", 16), "interval": _read(ep / "bInterval"),
        } for ep in sorted(iface.glob("ep_*"))]
        hids = []
        for hid in sorted(p for p in iface.iterdir() if p.is_dir() and p.name.count(":") == 2):
            try:
                descriptor = (hid / "report_descriptor").read_bytes()
            except OSError:
                descriptor = b""
            hids.append({
                "hidraw": [p.name for p in sorted((hid / "hidraw").glob("hidraw*"))],
                "descriptor": descriptor,
                "events": [{"node": ev.name, "name": _read(ev.parent / "name"),
                            "key": _read(ev.parent / "capabilities/key"), "rel": _read(ev.parent / "capabilities/rel"),
                            "abs": _read(ev.parent / "capabilities/abs"), "msc": _read(ev.parent / "capabilities/msc")}
                           for ev in sorted(hid.glob("input/input*/event*"))],
            })
        found.append({
            "number": int(_read(iface / "bInterfaceNumber") or "0", 16),
            "class": "/".join(_read(iface / f) for f in ("bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol")),
            "endpoints": endpoints,
            "hids": hids,
        })
    return found


def fingerprint(usb):
    """Short id of a device's firmware build: tells apart models that share a USB id."""
    digest = hashlib.sha256(_read(usb / "bcdDevice").encode())
    for iface in interfaces(usb):
        for hid in iface["hids"]:
            digest.update(hid["descriptor"])
    return digest.hexdigest()[:12]


def device_fingerprint(key):
    devices = usb_devices(key)
    return fingerprint(devices[0]) if devices else None


def _usage_name(page, usage):
    if page == 0x01 and usage in _DESKTOP:
        return f"{_PAGES[page]} / {_DESKTOP[usage]}"
    if page in _PAGES:
        return f"{_PAGES[page]} / 0x{usage:02x}"
    return f"page 0x{page:04x} / 0x{usage:02x}" + (" (vendor)" if page >= 0xFF00 else "")


def describe_report_descriptor(data):
    """Collections and the sizes of their input/output/feature reports, one line each."""
    lines, sizes, order = [], {}, []
    page = report_id = size = count = depth = 0
    usage = None
    i = 0

    def flush():
        for key in order:
            rid, kind = key
            lines.append("  " * depth + f"  report {rid or '-'}: {kind} {sizes[key] // 8} bytes"
                         + (f" (+{sizes[key] % 8} bits)" if sizes[key] % 8 else ""))
        sizes.clear()
        order.clear()

    while i < len(data):
        prefix = data[i]
        if prefix == 0xFE:  # long item
            i += 3 + (data[i + 1] if i + 1 < len(data) else 0)
            continue
        length = (0, 1, 2, 4)[prefix & 3]
        value = int.from_bytes(data[i + 1:i + 1 + length], "little")
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        i += 1 + length
        if kind == 1:  # global
            if tag == 0:
                page = value
            elif tag == 7:
                size = value
            elif tag == 8:
                report_id = value
            elif tag == 9:
                count = value
        elif kind == 2 and tag == 0:  # local usage
            usage = value
        elif kind == 0:  # main
            if tag in _MAIN:
                key = (report_id, _MAIN[tag])
                if key not in sizes:
                    order.append(key)
                    sizes[key] = 0
                sizes[key] += size * count
            elif tag == 0xA:
                flush()
                lines.append("  " * depth + f"collection: {_usage_name(page, usage or 0)}")
                depth += 1
            elif tag == 0xC:
                flush()
                depth = max(0, depth - 1)
            usage = None
    flush()
    return lines
