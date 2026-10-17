"""Backups of the settings stored in a mouse, as small JSON files.

A backup holds the mouse's whole settings area (vendor.SETTINGS_SIZE bytes):
everything Mousekit can change in the mouse. Before its first change to a
mouse, Mousekit keeps one automatically in BACKUP_DIR.
"""

import json
import os
import time
from pathlib import Path

from . import __version__, models, usbinfo

FORMAT = 1
BACKUP_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "mousekit" / "backups"


def make(key, settings):
    model = models.identify(key)
    return {
        "mousekit_backup": FORMAT,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mousekit": __version__,
        "usb_id": key,
        "model": model["name"] if model else "",
        "fingerprint": usbinfo.device_fingerprint(key),
        "settings": settings.hex(),
    }


def save(path, backup):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(backup, indent=2) + "\n")
    tmp.replace(path)


def load(path, key, size):
    """The backup at `path` if it's a backup of mouse `key`; raises ValueError otherwise."""
    try:
        backup = json.loads(Path(path).read_text())
        settings = bytes.fromhex(backup["settings"])
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("this isn't a Mousekit backup")
    if backup.get("mousekit_backup") != FORMAT:
        raise ValueError("this backup comes from a newer Mousekit")
    if backup.get("usb_id") != key:
        raise ValueError(f"this backup is of another mouse ({backup.get('model') or backup.get('usb_id')})")
    if len(settings) != size:
        raise ValueError("this backup is incomplete")
    backup["data"] = settings
    return backup


def default_name(key):
    model = models.identify(key)
    name = (model["name"] if model else key).lower().replace(" ", "-").replace(":", "-")
    return f"mousekit-backup-{name}-{time.strftime('%Y-%m-%d')}.json"


def first_path(key):
    """Where the automatic backup from before Mousekit's first change to this mouse goes."""
    return BACKUP_DIR / f"{key.replace(':', '-')}-before-first-change.json"
