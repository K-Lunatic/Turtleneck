#!/usr/bin/env python3
"""Create a safe local Moodle migration report for a future school module."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.moodle_migration import build_manifest, write_manifest
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_site import module_for
from providers.request_metrics import RequestMetrics, measure_requests
from providers.credentials import load_active_alias, site_key
from scripts.sync_tls import _login_with_retries


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a secret-free Moodle module proposal")
    parser.add_argument("--base-url", required=True, help="학교 Moodle 주소")
    parser.add_argument("--account-alias", help="저장된 학교 계정 별칭")
    parser.add_argument("--output", required=True, help="로컬 JSON 리포트 경로")
    args = parser.parse_args()

    site = site_key(args.base_url)
    alias = args.account_alias or load_active_alias(site)
    metrics = RequestMetrics()
    with measure_requests(metrics):
        _username, session = _login_with_retries(args.base_url, stored_only=True,
                                                 profile_alias=alias)
        provider = MoodleTLSProvider(session)
        courses = provider.get_courses(_username)
        activities = provider.get_activity_catalog(_username)
    manifest = build_manifest(args.base_url, module_for(args.base_url), courses, activities,
                              metrics.snapshot())
    target = write_manifest(args.output, manifest)
    print(f"마이그레이션 리포트 저장 완료 · 활동 {len(activities)}개 · {target}")
    print("이 파일에는 학교 모듈 검토에 필요한 요약만 있으며, 원문·계정·쿠키·강좌 식별자는 포함하지 않아요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
