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


def _changes(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, list]:
    """Summarize visible structure changes without fetching activity details."""
    old_sections = {str(item.get("id")): item for item in (previous or {}).get("sections", [])}
    new_sections = {str(item.get("id")): item for item in current.get("sections", [])}
    result = {
        "sectionsAdded": [], "sectionsRemoved": [], "sectionsRenamed": [],
        "activitiesAdded": [], "activitiesRemoved": [], "activitiesRenamed": [],
        "activityTypesChanged": [],
    }
    for key in sorted(new_sections.keys() - old_sections.keys()):
        result["sectionsAdded"].append(new_sections[key].get("name", ""))
    for key in sorted(old_sections.keys() - new_sections.keys()):
        result["sectionsRemoved"].append(old_sections[key].get("name", ""))
    for key in sorted(old_sections.keys() & new_sections.keys()):
        old_section, new_section = old_sections[key], new_sections[key]
        if old_section.get("name") != new_section.get("name"):
            result["sectionsRenamed"].append({"from": old_section.get("name", ""),
                                               "to": new_section.get("name", "")})
        old_activities = {str(item.get("id")): item for item in old_section.get("activities", [])}
        new_activities = {str(item.get("id")): item for item in new_section.get("activities", [])}
        for activity_id in sorted(new_activities.keys() - old_activities.keys()):
            item = new_activities[activity_id]
            result["activitiesAdded"].append({"section": new_section.get("name", ""),
                                               "name": item.get("name", ""),
                                               "type": item.get("type", "")})
        for activity_id in sorted(old_activities.keys() - new_activities.keys()):
            item = old_activities[activity_id]
            result["activitiesRemoved"].append({"section": old_section.get("name", ""),
                                                 "name": item.get("name", ""),
                                                 "type": item.get("type", "")})
        for activity_id in sorted(old_activities.keys() & new_activities.keys()):
            old_item, new_item = old_activities[activity_id], new_activities[activity_id]
            if old_item.get("name") != new_item.get("name"):
                result["activitiesRenamed"].append({"from": old_item.get("name", ""),
                                                     "to": new_item.get("name", ""),
                                                     "section": new_section.get("name", "")})
            if old_item.get("type") != new_item.get("type"):
                result["activityTypesChanged"].append({"name": new_item.get("name", ""),
                                                        "from": old_item.get("type", ""),
                                                        "to": new_item.get("type", "")})
    return result


def change_message(changes: Mapping[str, list]) -> str:
    labels = (
        ("sectionsAdded", "토픽 추가"), ("sectionsRemoved", "토픽 삭제"),
        ("sectionsRenamed", "토픽 이름 변경"), ("activitiesAdded", "활동 추가"),
        ("activitiesRemoved", "활동 삭제"), ("activitiesRenamed", "활동 이름 변경"),
        ("activityTypesChanged", "활동 유형 변경"),
    )
    parts = [f"{label} {len(changes.get(key, []))}건" for key, label in labels if changes.get(key)]
    return ", ".join(parts) if parts else "변경 없음"


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
    previous_snapshot = (previous or {}).get("snapshot")
    changes = _changes(previous_snapshot, snapshot) if old and previous_snapshot else {}
    message = (change_message(changes) if previous_snapshot else "구조 변경 있음") if old and old != current else "변경 없음"
    return {"ok": True, "courseId": external_id, "courseName": course.get("name"),
            "fingerprint": current, "changed": bool(old) and old != current,
            "snapshot": snapshot, "changes": changes, "changeMessage": message}
