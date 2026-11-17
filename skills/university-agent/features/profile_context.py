"""Choose a local school profile from the course named in a request."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from providers.credentials import list_profiles


def _normal(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _course_names(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            return [str(row[0]) for row in connection.execute("SELECT name FROM courses WHERE name IS NOT NULL")]
    except (OSError, sqlite3.Error):
        return []


def select_profile(text: str, *, site: str | None = None, alias: str | None = None) -> dict[str, Any]:
    """Return selected/ambiguous profile metadata; never reads a secret."""
    profiles = list_profiles()
    if site or alias:
        profiles = [item for item in profiles if (not site or item["site"] == site)
                    and (not alias or item["alias"] == alias)]
    if site or alias:
        if len(profiles) == 1:
            return {"status": "selected", "profile": profiles[0]}
        if len(profiles) > 1:
            return {"status": "ambiguous", "profiles": profiles}
    query = _normal(text)
    matches = []
    for profile in profiles:
        names = [name for name in _course_names(Path(str(profile["dbPath"]))) if len(_normal(name)) >= 2]
        if any(_normal(name) in query for name in names):
            matches.append(profile)
    unique = {(item["site"], item["alias"]): item for item in matches}
    if len(unique) == 1:
        return {"status": "selected", "profile": next(iter(unique.values()))}
    if len(unique) > 1:
        return {"status": "ambiguous", "profiles": list(unique.values())}
    active = [item for item in profiles if item.get("active")]
    if len(active) == 1:
        return {"status": "selected", "profile": active[0]}
    if len(active) > 1:
        return {"status": "ambiguous", "profiles": active}
    return {"status": "none", "profiles": profiles}
