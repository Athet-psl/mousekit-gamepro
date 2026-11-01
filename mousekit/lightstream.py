"""Mousekit's own lighting effects, streamed frame by frame into a mouse's DPI colour slots."""

import time
from collections import deque

from . import effects, vendor


class EffectRunner:
    """Streams one of Mousekit's own lighting effects into a mouse's DPI colour slots."""

    def __init__(self, key, node, light, read_inputs=True):
        self.key = key
        self.node = node
        self.light = light
        self.fd = vendor.open_channel(node, read_inputs)
        self.start = time.monotonic()
        self.clicks = deque(maxlen=16)
        self.sent = None
        self.next_frame = 0.0
        try:
            vendor.send(self.fd, vendor.stream_start_packet())
        except OSError:
            self.fd.close()
            raise

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
        return self.fd.fileno()

    def readable(self):
        """Input reports on the vendor interface: buttons programmed as media keys, DPI buttons."""
        while True:
            report = self.fd.read_nowait()
            if not report:
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
        self.fd.close()


def apply_once(node, light):
    """Send a firmware lighting setting live to the mouse at `node`."""
    channel = vendor.open_channel(node, inputs=False)
    try:
        vendor.apply_lighting(channel, light)
    finally:
        channel.close()
