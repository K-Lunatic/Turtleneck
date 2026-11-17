"""Public Coursemos institution candidates; not a live support guarantee."""
from __future__ import annotations

import json
import re
from pathlib import Path


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "coursemos_institutions.json"


def load_registry() -> dict:
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("listedInstitutions"), list):
        raise ValueError("코스모스 기관 목록 형식이 올바르지 않아요.")
    return value


def find_candidates(query: str, *, limit: int = 10) -> list[str]:
    if not isinstance(query, str) or not query.strip():
        return []
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("기관 검색 결과 수는 1~50개여야 해요.")
    needle = re.sub(r"\s+", "", query).casefold()
    rows = load_registry().get("listedInstitutions", [])
    return [name for name in rows if needle in re.sub(r"\s+", "", str(name)).casefold()][:limit]
