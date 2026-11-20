"""Optional native parsers used by the normal Moodle sync path.

The Rust library is an optimization only. Missing or incompatible native files
must leave the existing Python parser untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys


def _roots() -> list[Path]:
    roots = [Path(__file__).resolve().parents[3]]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.insert(0, Path(bundle_root))
    return roots


def _load_backend():
    for root in _roots():
        directory = root / "experiments" / "rust-core"
        backend_path = directory / "backend.py"
        if not backend_path.is_file():
            continue
        module_name = "turtleneck_optional_rust_backend"
        previous_path = list(sys.path)
        sys.path.insert(0, str(directory))
        try:
            spec = importlib.util.spec_from_file_location(module_name, backend_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except (ImportError, OSError, AttributeError, FileNotFoundError):
            continue
        finally:
            sys.path[:] = previous_path
    return None


@contextmanager
def activate():
    """Install measured Rust activity/overview parsers for one sync only."""
    backend = _load_backend()
    if backend is None:
        yield ()
        return
    try:
        with backend.activate(modules=("activity", "overview")) as enabled:
            yield enabled
    except (ImportError, OSError, AttributeError, FileNotFoundError):
        # A standalone build without the optional native artifact uses Python.
        yield ()
