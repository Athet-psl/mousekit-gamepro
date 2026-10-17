import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mousekit import backups, vendor


class FakeMouse:
    """The settings area as a bytearray behind read_register / write_register / commit."""

    def __init__(self, data):
        self.memory = bytearray(data)
        self.writes = []

    def __enter__(self):
        self.patches = [
            patch.object(vendor, "read_register", lambda fd, a, n: bytes(self.memory[a:a + n])),
            patch.object(vendor, "write_register", self._write),
            patch.object(vendor, "commit", lambda fd: self.writes.append("commit")),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def _write(self, fd, address, data):
        self.writes.append(address)
        self.memory[address:address + len(data)] = data


class RestoreTest(unittest.TestCase):
    def test_writes_only_changed_blocks_and_commits(self):
        backup = bytes(range(256))
        changed = bytearray(backup)
        changed[0x18] = 0x19
        changed[0x41] = 0
        with FakeMouse(changed) as mouse:
            self.assertEqual(vendor.restore_settings(None, backup), 2)
        self.assertEqual(mouse.writes, [0x18, 0x40, "commit"])
        self.assertEqual(bytes(mouse.memory), backup)

    def test_nothing_to_do(self):
        with FakeMouse(bytes(256)) as mouse:
            self.assertEqual(vendor.restore_settings(None, bytes(256)), 0)
        self.assertEqual(mouse.writes, [])

    def test_refuses_another_model(self):
        other = bytearray(256)
        other[2] = 0x41  # the header carries the model's USB ids
        with FakeMouse(bytes(256)) as mouse:
            with self.assertRaises(ValueError):
                vendor.restore_settings(None, bytes(other))
        self.assertEqual(mouse.writes, [])


class BackupFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "backup.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        backups.save(self.path, {"mousekit_backup": 1, "usb_id": "30fa:1440", "settings": bytes(range(256)).hex()})
        self.assertEqual(backups.load(self.path, "30fa:1440", 256)["data"], bytes(range(256)))

    def test_rejects(self):
        cases = {
            "another mouse": {"mousekit_backup": 1, "usb_id": "046d:c077", "settings": "00" * 256},
            "newer format": {"mousekit_backup": 2, "usb_id": "30fa:1440", "settings": "00" * 256},
            "incomplete": {"mousekit_backup": 1, "usb_id": "30fa:1440", "settings": "00" * 16},
            "not a backup": {"hello": "world"},
        }
        for name, content in cases.items():
            self.path.write_text(json.dumps(content))
            with self.subTest(name), self.assertRaises(ValueError):
                backups.load(self.path, "30fa:1440", 256)


if __name__ == "__main__":
    unittest.main()
