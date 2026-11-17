"""Small, dependency-free helpers for device-local private files."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def _path(value: str | Path) -> Path:
    # Tests and callers may temporarily override os.name to exercise Windows
    # DPAPI on another host; keep an already-created host path intact.
    return value if isinstance(value, Path) else Path(value)


def private_dir(path: str | Path) -> Path:
    directory = _path(path).expanduser()
    if directory.is_symlink():
        raise PermissionError(f"private directory must not be a symlink: {directory}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and stat.S_IMODE(directory.stat().st_mode) != 0o700:
        os.chmod(directory, 0o700)
    return directory


def private_file(path: str | Path, mode: int = 0o600) -> Path:
    target = _path(path).expanduser()
    if target.is_symlink():
        raise PermissionError(f"private file must not be a symlink: {target}")
    if target.exists() and os.name != "nt" and stat.S_IMODE(target.stat().st_mode) != mode:
        os.chmod(target, mode)
    return target


def atomic_write(path: str | Path, data: bytes, mode: int = 0o600) -> Path:
    target = private_file(path, mode)
    private_dir(target.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = target.parent / os.path.basename(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        if os.name != "nt" and stat.S_IMODE(target.stat().st_mode) != mode:
            os.chmod(target, mode)
        return target
    finally:
        if descriptor != -1:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: str | Path, text: str, mode: int = 0o600) -> Path:
    return atomic_write(path, text.encode("utf-8"), mode)
