"""The vendor HID channel of a mouse, the same on Linux and Windows.

A Channel sends and reads feature reports and reads the input reports the
mouse sends on its vendor interface (DPI button events, keys programmed in
the mouse). On Linux that is one /dev/hidrawN; on Windows it is several HID
collections of the same USB interface: features on the vendor-page one,
input reports on the others.
"""

import os
import sys
import time

WINDOWS = sys.platform == "win32"

# Vendor usage page 0xFF01 declaring feature report 0x07: the config channel.
CONFIG_PAGE = 0xFF01
CONFIG_REPORT = 0x07
_CONFIG_PAGE_ITEM = bytes([0x06, 0x01, 0xFF])
_CONFIG_REPORT_ITEM = bytes([0x85, CONFIG_REPORT])


if WINDOWS:
    from . import winhid

    def find(key, vendor_id):
        """The id of mouse "vvvv:pppp"'s config channel (its feature collection's path), or None."""
        if int(key.split(":")[0], 16) != vendor_id:
            return None
        for coll in winhid.collections(key):
            if coll.usage_page == CONFIG_PAGE and CONFIG_REPORT in coll.report_ids["feature"]:
                return coll.path
        return None

    class Channel:
        def __init__(self, node, inputs=True):
            self.node = node
            self.feature = winhid.Device(node)
            config = winhid.describe(node)
            self.inputs = []
            if not inputs:
                return
            try:
                for coll in winhid.collections(config.key):
                    # Input collections of the same interface; the system keeps the keyboard one for itself.
                    if coll.interface != config.interface or coll.path == node or not coll.input_size:
                        continue
                    if coll.usage_page == 0x01 and coll.usage in (0x02, 0x06):
                        continue
                    try:
                        self.inputs.append(winhid.Device(coll.path))
                    except OSError:
                        pass
            except BaseException:
                self.close()
                raise

        def set_feature(self, data):
            self.feature.set_feature(data)

        def get_feature(self, report_id, size):
            return self.feature.get_feature(report_id, size)

        def read_nowait(self):
            """The next input report, or None. Raises OSError once the mouse is gone."""
            for device in self.inputs:
                report = device.read(0)
                if report:
                    return report
            return None

        def fileno(self):
            return None  # nothing to select on: poll read_nowait()

        def close(self):
            for device in [self.feature, *self.inputs]:
                try:
                    device.close()
                except OSError:
                    pass
            self.inputs = []

else:
    import fcntl
    from pathlib import Path

    def _hidioc(code, size):
        return (3 << 30) | (size << 16) | (ord("H") << 8) | code

    def find(key, vendor_id):
        """The /dev/hidrawN carrying mouse "vvvv:pppp"'s config channel, if accessible."""
        vendor, product = (int(part, 16) for part in key.split(":"))
        if vendor != vendor_id:
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
            if (_CONFIG_PAGE_ITEM in descriptor and _CONFIG_REPORT_ITEM in descriptor
                    and os.access(node, os.R_OK | os.W_OK)):
                return node
        return None

    class Channel:
        def __init__(self, node, inputs=True):
            self.node = node
            self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)

        def set_feature(self, data):
            fcntl.ioctl(self.fd, _hidioc(0x06, len(data)), bytes(data))

        def get_feature(self, report_id, size):
            buf = bytearray(size)
            buf[0] = report_id
            got = fcntl.ioctl(self.fd, _hidioc(0x07, size), buf, True)
            return bytes(buf[:got])

        def read_nowait(self):
            try:
                return os.read(self.fd, 64)
            except BlockingIOError:
                return None

        def fileno(self):
            return self.fd

        def close(self):
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None


def sleep(seconds):
    if seconds > 0:
        time.sleep(seconds)
