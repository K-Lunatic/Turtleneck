#!/usr/bin/env python3
"""Persist one read-only Canvas snapshot into its private profile database."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.canvas_auth import authenticated_canvas
from providers.canvas_provider import normalize_canvas_domain
from providers.credentials import profile_db_path, site_key
from storage.local_db import LocalDatabase


def sync_snapshot(domain: str | None, alias: str, *, force_input: bool = False) -> dict:
    selected, provider = authenticated_canvas(domain, alias, force_input=force_input)
    user = provider.get_user()
    if not isinstance(user, dict) or user.get("id") is None:
        raise ValueError("Canvas 사용자 정보를 확인하지 못했어요.")
    normalized = normalize_canvas_domain(domain or provider.client.domain)
    site = site_key(normalized)
    user_id = f"canvas:{site}:{user['id']}"
    snapshot = provider.snapshot(user_id)
    path = profile_db_path(site, selected)
    now = datetime.now(timezone.utc).isoformat()
    with closing(LocalDatabase(path)) as database:
        database.upsert_tls_snapshot(
            user_id,
            snapshot["courses"],
            snapshot["assignments"],
            [],
            str(user.get("name") or user_id),
            None,
            now=now,
            notices=snapshot["notices"],
            resources=snapshot["resources"],
        )
        database.merge_sync_state(user_id, {
            "provider": "canvas",
            "canvas_site": site,
            "canvas_synced_at": now,
        })
    return {
        "status": "READY",
        "source": "canvas",
        "accountAlias": selected,
        "user": {"id": user.get("id"), "name": user.get("name")},
        "counts": {key: len(value) for key, value in snapshot.items()},
        "writes": "disabled",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Canvas 읽기 데이터를 이 계정의 로컬 학사 DB에 저장")
    parser.add_argument("--domain")
    parser.add_argument("--account-alias", default="default")
    parser.add_argument("--force", action="store_true", help="보안 토큰 입력 화면을 다시 엽니다")
    args = parser.parse_args()
    result = sync_snapshot(args.domain, args.account_alias, force_input=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
