import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.canvas_sync import sync_snapshot
from storage.local_db import LocalDatabase


class FakeCanvasProvider:
    client = type("Client", (), {"domain": "https://canvas.example.edu"})()

    def get_user(self):
        return {"id": 7, "name": "학생"}

    def snapshot(self, _user_id=None):
        course = {"id": "canvas-course-42", "externalId": "canvas:42", "name": "운영체제", "source": "canvas"}
        return {
            "courses": [course],
            "assignments": [{"id": "canvas-assignment-3", "externalId": "3", "courseId": course["id"],
                             "title": "보고서", "description": "", "dueAt": None,
                             "submissionStatus": "UNKNOWN", "source": "canvas"}],
            "resources": [{"id": "canvas-resource-9", "externalId": "9", "courseId": course["id"],
                           "title": "강의자료", "fileName": "lecture.pdf", "extension": "pdf",
                           "mimeType": "application/pdf", "remotePath": "https://canvas.example.edu/files/9",
                           "downloadStatus": "NOT_DOWNLOADED", "source": "canvas"}],
            "notices": [{"id": "canvas-notice-10", "externalId": "10", "courseId": course["id"],
                         "title": "공지", "content": "시험", "publishedAt": "2026-11-01T00:00:00Z",
                         "source": "canvas"}],
            "modules": [],
        }


class CanvasSyncTests(unittest.TestCase):
    def test_snapshot_is_persisted_in_site_profile_without_secrets(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "canvas.db"
            with patch("scripts.canvas_sync.authenticated_canvas", return_value=("main", FakeCanvasProvider())), \
                 patch("scripts.canvas_sync.profile_db_path", return_value=db_path):
                result = sync_snapshot("https://canvas.example.edu", "main")
            self.assertEqual(result["status"], "READY")
            with closing(LocalDatabase(db_path, read_only=True)) as database:
                self.assertEqual(database.get_courses("canvas:canvas.example.edu:7")[0]["source"], "canvas")
                self.assertEqual(database.get_assignments("canvas:canvas.example.edu:7")[0]["source"], "canvas")
                self.assertEqual(database.get_resources("canvas:canvas.example.edu:7")[0]["source"], "canvas")
                self.assertEqual(database.get_sync_state("canvas:canvas.example.edu:7")["provider"], "canvas")
            self.assertNotIn("token", json.dumps(result, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
