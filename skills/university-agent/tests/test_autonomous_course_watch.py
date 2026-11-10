import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.autonomous_course_watch import refresh


class FakeProvider:
    def __init__(self, blueprint):
        self.blueprint = blueprint

    def get_autonomous_courses(self, _user_id):
        return [{"externalId": "42", "role": "운영자", "ownerControlsVisible": True, "name": "자율강좌"}]

    def get_course_structure(self, _external_id):
        return self.blueprint


def blueprint(activity_name="자료 안내", *, extra=False):
    activities = [{"externalId": "a1", "type": "label", "name": activity_name}]
    if extra:
        activities.append({"externalId": "a2", "type": "quiz", "name": "연습 문제"})
    return {"courseId": "42", "sections": [{"id": "s1", "name": "1주차", "activities": activities}]}


class AutonomousCourseWatchTests(unittest.TestCase):
    URL = "https://tls.kku.ac.kr/course/view.php?id=42"

    def test_first_read_has_no_change_and_second_read_summarizes_structure(self):
        first = refresh(FakeProvider(blueprint()), "user", self.URL)
        self.assertTrue(first["ok"])
        self.assertFalse(first["changed"])

        second = refresh(FakeProvider(blueprint("자료 안내 수정", extra=True)), "user", self.URL,
                         {"fingerprint": first["fingerprint"], "snapshot": first["snapshot"]})
        self.assertTrue(second["changed"])
        self.assertEqual(second["changes"]["activitiesAdded"][0]["name"], "연습 문제")
        self.assertEqual(second["changes"]["activitiesRenamed"][0]["to"], "자료 안내 수정")
        self.assertIn("활동 추가 1건", second["changeMessage"])
        self.assertIn("활동 이름 변경 1건", second["changeMessage"])

    def test_old_fingerprint_without_snapshot_does_not_claim_exact_details(self):
        current = refresh(FakeProvider(blueprint("변경된 자료")), "user", self.URL,
                          {"fingerprint": "old-but-no-snapshot"})
        self.assertTrue(current["changed"])
        self.assertEqual(current["changeMessage"], "구조 변경 있음")
        self.assertEqual(current["changes"], {})


if __name__ == "__main__":
    unittest.main()
