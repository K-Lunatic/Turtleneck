import json
import os
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import canvas_credentials
from providers.canvas_provider import CanvasApiError, CanvasClient, CanvasProvider, normalize_canvas_domain


class Response:
    def __init__(self, payload, *, link=None, url="https://canvas.example.edu"):
        self._payload = json.dumps(payload).encode()
        self.headers = Message()
        if link:
            self.headers["Link"] = link
        self._url = url

    def read(self, _size=-1):
        data, self._payload = self._payload, b""
        return data

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class CanvasFixture:
    def __init__(self):
        self.requests = []
        self.pages = {}

    def __call__(self, request, timeout=0):
        self.requests.append((request.full_url, request.headers, timeout))
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/v1/users/self/profile":
            return Response({"id": 7, "name": "학생"})
        if parsed.path == "/api/v1/courses":
            return Response([{
                "id": 42,
                "name": "운영체제",
                "course_code": "CS42",
                "enrollments": [{"computed_current_grade": "A+", "computed_current_score": 97}],
            }])
        if parsed.path == "/api/v1/courses/42/assignments":
            return Response([
                {"id": 3, "name": "보고서", "due_at": "2026-12-01T14:00:00Z",
                 "submission": {"submitted_at": "2026-11-01T10:00:00Z", "late": False}},
                {"id": 4, "name": "실습", "submission": None},
            ])
        if parsed.path == "/api/v1/courses/42/modules":
            return Response([{"id": 5, "name": "1주차", "position": 1, "items": [{"id": 8}]}])
        if parsed.path == "/api/v1/courses/42/files":
            return Response([{"id": 9, "filename": "lecture.pdf", "display_name": "강의자료",
                              "content-type": "application/pdf", "size": 123,
                              "url": "https://canvas.example.edu/files/9/download"}])
        if parsed.path == "/api/v1/courses/42/discussion_topics":
            self.assert_only_announcements(query)
            return Response([{"id": 10, "title": "공지", "message": "시험 안내",
                              "posted_at": "2026-11-02T10:00:00Z"}])
        if parsed.path == "/api/v1/paged":
            if query.get("page") == ["2"]:
                return Response([{"id": 2}])
            return Response([{"id": 1}], link='<https://canvas.example.edu/api/v1/paged?page=2>; rel="next"')
        raise AssertionError(f"unexpected Canvas request: {request.full_url}")

    @staticmethod
    def assert_only_announcements(query):
        if query.get("only_announcements") != ["true"]:
            raise AssertionError(f"announcement filter missing: {query}")


class CanvasProviderTests(unittest.TestCase):
    def test_normalize_domain_requires_https_origin(self):
        self.assertEqual(normalize_canvas_domain("canvas.example.edu"), "https://canvas.example.edu")
        with self.assertRaises(ValueError):
            normalize_canvas_domain("http://canvas.example.edu")
        with self.assertRaises(ValueError):
            normalize_canvas_domain("https://canvas.example.edu/canvas")

    def test_client_uses_bearer_auth_and_follows_same_origin_pages(self):
        fixture = CanvasFixture()
        client = CanvasClient("canvas.example.edu", "secret-token", opener=fixture)
        self.assertEqual(client.get_all("/paged"), [{"id": 1}, {"id": 2}])
        self.assertEqual(len(fixture.requests), 2)
        self.assertEqual(fixture.requests[0][1]["Authorization"], "Bearer secret-token")

    def test_provider_normalizes_courses_assignments_and_materials(self):
        fixture = CanvasFixture()
        provider = CanvasProvider(CanvasClient("https://canvas.example.edu", "secret-token", opener=fixture))
        courses = provider.get_courses()
        self.assertEqual(courses[0]["id"], "canvas-course-42")
        self.assertEqual(courses[0]["currentGrade"], "A+")

        assignments = provider.get_assignments()
        self.assertEqual([item["submissionStatus"] for item in assignments], ["SUBMITTED", "UNKNOWN"])
        self.assertEqual(assignments[0]["dueAt"], "2026-12-01T14:00:00Z")

        self.assertEqual(provider.get_modules("canvas-course-42")[0]["name"], "1주차")
        self.assertEqual(provider.get_course_resources("canvas-course-42")[0]["fileName"], "lecture.pdf")
        self.assertEqual(provider.get_course_notices("canvas-course-42")[0]["title"], "공지")
        self.assertEqual(provider.get_resources("student")[0]["fileName"], "lecture.pdf")
        self.assertEqual(provider.get_notices("student")[0]["title"], "공지")
        self.assertEqual(provider.get_lectures("student"), [])
        self.assertFalse(hasattr(provider, "submit_assignment"))

    def test_next_page_on_another_origin_is_rejected(self):
        class BadLink(CanvasFixture):
            def __call__(self, request, timeout=0):
                parsed = urlsplit(request.full_url)
                if parsed.path == "/api/v1/paged":
                    return Response([{"id": 1}], link='<https://evil.example/api/v1/paged?page=2>; rel="next"')
                return super().__call__(request, timeout)

        with self.assertRaises(ValueError):
            CanvasClient("https://canvas.example.edu", "secret", opener=BadLink()).get_all("/paged")

    def test_token_marker_does_not_contain_plaintext_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canvas-accounts.json"
            with patch.object(canvas_credentials, "_config_path", return_value=path), \
                 patch.object(canvas_credentials, "_save_keychain_secret") as save_secret, \
                 patch.object(canvas_credentials.subprocess, "run",
                              return_value=SimpleNamespace(stdout="secret-token\n")) as run:
                canvas_credentials.save_token("secret-token", "본계정", "canvas.example.edu")
                self.assertNotIn("secret-token", path.read_text(encoding="utf-8"))
                with patch.object(canvas_credentials.subprocess, "run", return_value=SimpleNamespace(stdout="secret-token\n")):
                    self.assertEqual(canvas_credentials.load_token("본계정", "canvas.example.edu"), "secret-token")
                if os.name == "nt":
                    self.assertIn("protected", json.loads(path.read_text(encoding="utf-8"))["profiles"]["본계정"])
                    save_secret.assert_not_called()
                else:
                    save_secret.assert_called_once_with("university-agent/canvas-token/canvas.example.edu", "본계정", "secret-token")

    def test_canvas_accounts_are_separated_by_site(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "canvas-accounts.json"
            def security_result(command, **_kwargs):
                if "find-generic-password" in command:
                    token = "token-a" if any("canvas-a.example.edu" in part for part in command) else "token-b"
                    return SimpleNamespace(stdout=token + "\n")
                return SimpleNamespace(stdout="")

            with patch.object(canvas_credentials, "CONFIG_PATH", base), \
                 patch.object(canvas_credentials, "_save_keychain_secret", side_effect=lambda service, alias, token: security_result(("security", "add-generic-password", "-s", service, "-a", alias), input=token + "\n")), \
                 patch.object(canvas_credentials.subprocess, "run", side_effect=security_result):
                canvas_credentials.save_token("token-a", "main", "canvas-a.example.edu")
                canvas_credentials.save_token("token-b", "main", "canvas-b.example.edu")
                self.assertEqual(canvas_credentials.load_token("main", "canvas-a.example.edu"), "token-a")
                self.assertEqual(canvas_credentials.load_token("main", "canvas-b.example.edu"), "token-b")


if __name__ == "__main__":
    unittest.main()
