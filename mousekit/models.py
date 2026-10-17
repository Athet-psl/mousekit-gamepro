"""Mouse models Mousekit knows, recognised when they connect.

A USB id names the chip and its firmware more than the product: several
brands build mice on the same Instant (30fa) chip, and one brand can reuse an
id for several models. So a model is matched by its USB id and, where ids are
shared, by the fingerprint of its USB descriptors (usbinfo.fingerprint).
`mousekit --dump` prints both for a new model.

"verified" models have had their memory layout checked: only they get the
settings that are saved to the mouse.
"""

from . import usbinfo

MODELS = [
    {"key": "30fa:1440", "fingerprint": None, "name": "GamePro GM500W", "art": "gm500w", "verified": True},
]


def identify(key, fingerprint=None):
    """The known model of a connected mouse, or None."""
    candidates = [m for m in MODELS if m["key"] == key]
    if not candidates:
        return None
    if any(m["fingerprint"] for m in candidates):
        fingerprint = fingerprint or usbinfo.device_fingerprint(key)
        for model in candidates:
            if model["fingerprint"] == fingerprint:
                return model
    return next((m for m in candidates if not m["fingerprint"]), None)


def display_name(key, system_name):
    model = identify(key)
    return model["name"] if model else system_name
