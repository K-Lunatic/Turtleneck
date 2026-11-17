#!/usr/bin/env python3
"""Validate a stored Moodle Web Service token without opening a login form."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.moodle_api import MoodleApiError, MoodleWebServiceClient
from providers.moodle_api_credentials import DEFAULT_SERVICE, load_token
from providers.moodle_api_auth import normalize_moodle_domain
from providers.credentials import normalize_alias, site_key


def check(base_url: str, alias: str, service: str) -> dict[str, object]:
    domain = normalize_moodle_domain(base_url)
    token = load_token(alias, site_key(domain), service=service)
    info = MoodleWebServiceClient(domain, token).site_info()
    if not isinstance(info, dict) or info.get("userid") is None:
        raise RuntimeError("저장된 토큰은 응답했지만 Moodle 사용자 정보를 확인하지 못했어요.")
    return {"status": "READY", "site": site_key(domain), "alias": normalize_alias(alias),
            "service": service, "userId": info["userid"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="저장된 Moodle API 토큰만 검증")
    parser.add_argument("--base-url", default="https://tls.kku.ac.kr")
    parser.add_argument("--account-alias", default="default")
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.base_url, args.account_alias, args.service), ensure_ascii=False, indent=2))
    except (OSError, KeyError, ValueError, MoodleApiError, ConnectionError, RuntimeError) as error:
        print(json.dumps({"status": "NOT_READY", "message": str(error)}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
