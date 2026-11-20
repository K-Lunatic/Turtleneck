"""The optional Rust accelerator must never be required for sync."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from providers import native_backend


class NativeBackendTests(unittest.TestCase):
    def test_missing_backend_is_a_noop(self):
        with patch.object(native_backend, "_load_backend", return_value=None):
            with native_backend.activate() as enabled:
                self.assertEqual(enabled, ())

    def test_measured_modules_are_forwarded(self):
        class Backend:
            def activate(self, *, modules):
                self.modules = modules
                from contextlib import nullcontext
                return nullcontext(("activity", "overview"))

        backend = Backend()
        with patch.object(native_backend, "_load_backend", return_value=backend):
            with native_backend.activate() as enabled:
                self.assertEqual(enabled, ("activity", "overview"))
        self.assertEqual(backend.modules, ("activity", "overview"))


if __name__ == "__main__":
    unittest.main()
