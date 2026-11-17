import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.local_db import LocalDatabase
from storage.private_files import atomic_write_text, private_file


class PrivateFileTests(unittest.TestCase):
    def test_atomic_write_creates_private_file_and_replaces_complete_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "nested" / "state.json"
            atomic_write_text(target, '{"status":"READY"}\n')
            self.assertEqual(target.read_text(encoding="utf-8"), '{"status":"READY"}\n')
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)

    def test_symlink_is_not_followed_for_private_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "outside.txt"
            outside.write_text("keep", encoding="utf-8")
            target = root / "state.txt"
            target.symlink_to(outside)
            with self.assertRaises(PermissionError):
                private_file(target)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_symlink_directory_is_not_used_for_private_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / "outside"
            outside.mkdir()
            target = root / "private"
            target.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(PermissionError):
                atomic_write_text(target / "state.json", "nope")
            self.assertFalse((outside / "state.json").exists())

    def test_local_database_is_private_when_created(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "university.db"
            db = LocalDatabase(path)
            db.close()
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
