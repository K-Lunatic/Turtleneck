import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.moodle_migration import build_manifest, write_manifest


class MoodleMigrationTests(unittest.TestCase):
    def test_manifest_contains_only_safe_aggregate_observations(self):
        module = SimpleNamespace(key="standard_moodle", custom_viewers=False,
                                autonomous_course_path=None)
        manifest = build_manifest(
            "https://lms.example.edu",
            module,
            [{"id": "moodle-course-7", "name": "비밀 과목"}],
            [{"id": "moodle-course-7-1", "type": "resource", "title": "비밀 자료"},
             {"id": "moodle-course-7-2", "type": "mod_custom", "title": "비밀 활동"}],
            {"requests": 3, "response_body_bytes": 100},
        )
        text = json.dumps(manifest, ensure_ascii=False)
        self.assertEqual(manifest["site"]["host"], "lms.example.edu")
        self.assertEqual(manifest["observation"]["activityCount"], 2)
        self.assertNotIn("비밀 과목", text)
        self.assertNotIn("moodle-course-7", text)
        self.assertTrue(manifest["safety"]["credentialsIncluded"] is False)

    def test_write_manifest_creates_json_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = write_manifest(Path(directory) / "nested" / "migration.json", {"schema": "test"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], "test")


if __name__ == "__main__":
    unittest.main()
