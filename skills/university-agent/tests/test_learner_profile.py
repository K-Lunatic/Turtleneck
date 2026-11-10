import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from features.guidance import guidance_request
from storage.local_db import LocalDatabase


class LearnerProfileTests(unittest.TestCase):
    def test_pre_exam_summary_guidance_explains_fixed_markers_and_notability_consent(self):
        result = guidance_request("시험 전 정리본 만들어줘")
        self.assertTrue(result["needsPreExamSummary"])
        self.assertIn("누락", result["answer"])
        self.assertIn("Notability", result["answer"])
        self.assertIn("🔥", result["answer"])

    def test_autonomous_course_guidance_explains_manual_setup(self):
        result = guidance_request("자율강좌 설정 도와줘")
        self.assertTrue(result["needsAutonomousCourseSetup"])
        self.assertIn("강좌 만들기", result["answer"])
        self.assertIn("강좌 URL", result["answer"])
        self.assertIn("읽기 전용", result["answer"])
        self.assertNotIn("65513", result["answer"])

    def test_analysis_requires_consent_and_inventory_is_safe(self):
        result = guidance_request("자료구조 자료 분석해줘")
        self.assertTrue(result["needsLearningDiscoveryConsent"])
        self.assertNotIn("파일", result["data"] if "data" in result else {})

        inventory = guidance_request("사용 가능한 스킬과 자료 목록 알려줘")
        self.assertTrue(inventory["data"]["skills"])
        self.assertTrue(inventory["data"]["capabilities"])

    def test_profile_round_trip_merges_explicit_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            with closing(LocalDatabase(Path(folder) / "school.db")) as db:
                db.connection.execute(
                    "INSERT INTO users(id, external_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    ("u", "u", "학습자", "now", "now"),
                )
                db.connection.commit()
                saved = db.save_learner_profile("u", {
                    "learningStyle": "notability",
                    "preferredSources": ["Notability", "TLS"],
                    "consents": {"sourceAnalysis": True},
                })
                self.assertEqual(saved["learningStyle"], "notability")
                self.assertTrue(saved["consents"]["sourceAnalysis"])
                loaded = db.get_learner_profile("u")
                self.assertEqual(loaded["preferredSources"], ["Notability", "TLS"])
                self.assertFalse(loaded["consents"]["notabilityContent"])


if __name__ == "__main__":
    unittest.main()

