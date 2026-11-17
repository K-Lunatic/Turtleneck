"""Build a safe, non-identifying Moodle migration report for school modules."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit


SCHEMA = "turtleneck.moodle-migration/v1"


def build_manifest(base_url: str, module, courses: list[dict], activities: list[dict], metrics: dict | None = None) -> dict:
    """Summarize observed capability without exporting names, IDs or raw responses."""
    types = Counter(str(item.get("type") or "unknown") for item in activities)
    source_counts = Counter(str(item.get("source") or "unknown") for item in activities)
    host = (urlsplit(base_url).hostname or "").casefold()
    return {
        "schema": SCHEMA,
        "site": {
            "host": host,
            "provider": "moodle",
            "moduleKey": module.key,
        },
        "observation": {
            "courseCount": len(courses),
            "activityCount": len(activities),
            "activityTypes": dict(sorted(types.items())),
            "sourceCounts": dict(sorted(source_counts.items())),
            "customViewers": bool(module.custom_viewers),
            "autonomousCourseListing": bool(module.autonomous_course_path),
        },
        "optimization": {
            "unknownActivityTypes": sorted(kind for kind in types if kind == "unknown" or kind.startswith("unknown:")),
            "requestedReview": [
                "학교별 로그인·동영상·파일 권한 화면을 실제 사용 중 관찰한 뒤 모듈로 검토",
                "표준 Moodle 경로와 다른 활동 유형은 비밀값 없는 fixture로 재현",
            ],
        },
        "network": {
            key: metrics[key] for key in (
                "requests", "request_body_bytes", "response_body_bytes",
                "requests_by_kind", "response_body_bytes_by_kind",
                "peak_requests_per_second", "elapsed_seconds",
            ) if metrics and key in metrics
        },
        "safety": {
            "credentialsIncluded": False,
            "cookiesIncluded": False,
            "rawPagesIncluded": False,
            "courseNamesAndIdsIncluded": False,
            "originalFilesIncluded": False,
            "remoteWritesPerformed": False,
        },
    }


def write_manifest(path: str | Path, manifest: dict) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
