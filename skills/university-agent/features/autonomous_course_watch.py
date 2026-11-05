"""Read-only change tracking for the explicitly selected TLS autonomous course."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from features.autonomous_course_policy import course_external_id_from_url


def _snapshot(blueprint: Mapping[str, Any]) -> dict[str, Any]:
    sections = []
    for section in blueprint.get("sections", []):
        activities = [
            {
                "id": str(activity.get("externalId") or activity.get("id") or ""),
                "type": str(activity.get("type") or ""),
                "name": str(activity.get("name") or ""),
            }
            for activity in section.get("activities", [])
        ]
        sections.append({
            "id": str(section.get("id") or ""),
            "name": str(section.get("name") or ""),
            "activities": activities,
        })
    return {"courseId": str(blueprint.get("courseId") or ""), "sections": sections}


def structure_fingerprint(snapshot: Mapping[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh(provider: Any, user_id: str, course_url: str, previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Fetch only the visible structure after checking the selected course's owner controls."""
    external_id = course_external_id_from_url(course_url)
    course = next((item for item in provider.get_autonomous_courses(user_id)
                   if str(item.get("externalId")) == external_id), None)
    if course is None:
        return {"ok": False, "courseId": external_id, "reason": "선택한 자율강좌를 현재 계정에서 찾지 못했어요."}
    if course.get("role") not in {"운영자", "교수"} or course.get("ownerControlsVisible") is not True:
        return {"ok": False, "courseId": external_id, "reason": "자율강좌 운영 권한을 확인하지 못해 구조를 저장하지 않았어요."}
    snapshot = _snapshot(provider.get_course_structure(external_id))
    current = structure_fingerprint(snapshot)
    old = (previous or {}).get("fingerprint")
    return {"ok": True, "courseId": external_id, "courseName": course.get("name"),
            "fingerprint": current, "changed": bool(old) and old != current,
            "snapshot": snapshot}
