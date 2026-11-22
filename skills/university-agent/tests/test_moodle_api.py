import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.moodle_api import MoodleApiError, MoodleWebServiceClient
from providers import moodle_api_credentials
from providers.moodle_api_auth import normalize_moodle_domain
from scripts.connect_moodle_api import issue_token


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
        self.headers = {}

    def read(self, _limit=-1):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class MoodleApiTests(unittest.TestCase):
    def test_read_only_calls_use_post_and_never_put_token_in_url(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return Response({"site": "TLS", "userid": 42})

        client = MoodleWebServiceClient("https://tls.example", "secret-token", opener=opener)
        self.assertEqual(client.contents(7), {"site": "TLS", "userid": 42})
        request, timeout = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertNotIn("secret-token", request.full_url)
        self.assertIn(b"wstoken=secret-token", request.data)
        self.assertIn(b"courseid=7", request.data)

    def test_moodle_errors_are_normalized(self):
        def opener(_request, **_kwargs):
            return Response({"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "bad token"})

        with self.assertRaisesRegex(MoodleApiError, "bad token"):
            MoodleWebServiceClient("https://tls.example", "token", opener=opener).site_info()

    def test_oversized_moodle_response_is_reported_without_json_truncation(self):
        class OversizedResponse(Response):
            def __init__(self):
                self.status = 200
                self.headers = {}

            def read(self, limit=-1):
                return b"{" + b"x" * (limit + 1)

        with self.assertRaisesRegex(MoodleApiError, "너무 커서"):
            MoodleWebServiceClient(
                "https://tls.example", "token", opener=lambda *_args, **_kwargs: OversizedResponse()
            ).site_info()

    def test_declared_oversized_moodle_response_is_rejected_before_read(self):
        class DeclaredOversizedResponse(Response):
            def __init__(self):
                self.status = 200
                self.headers = {"Content-Length": str(16 * 1024 * 1024 + 1)}
                self.read_called = False

            def read(self, _limit=-1):
                self.read_called = True
                return b"{}"

        response = DeclaredOversizedResponse()
        with self.assertRaisesRegex(MoodleApiError, "너무 커서"):
            MoodleWebServiceClient(
                "https://tls.example", "token", opener=lambda *_args, **_kwargs: response
            ).site_info()
        self.assertFalse(response.read_called)

    def test_token_marker_does_not_contain_plaintext(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(moodle_api_credentials, "CONFIG_PATH", Path(folder) / "moodle-api-accounts.json"), \
             patch.object(moodle_api_credentials, "_save_keychain_secret"):
            path = moodle_api_credentials.CONFIG_PATH
            try:
                moodle_api_credentials.save_token("secret-token", "main", "tls.kku.ac.kr")
                self.assertNotIn("secret-token", path.read_text(encoding="utf-8"))
            finally:
                path.unlink(missing_ok=True)

    def test_moodle_domain_rejects_non_https_and_paths(self):
        self.assertEqual(normalize_moodle_domain("tls.example"), "https://tls.example")
        with self.assertRaises(ValueError):
            normalize_moodle_domain("http://tls.example")
        with self.assertRaises(ValueError):
            normalize_moodle_domain("https://tls.example/login")

    def test_token_service_denial_is_actionable_without_echoing_server_text(self):
        def opener(_request, **_kwargs):
            return Response({"error": "지원하지 않는 경로 전환이 발견되었기 때문에, 스크립트 실행이 중지되었음"})

        with self.assertRaisesRegex(RuntimeError, "Web Service 토큰 발급을 허용하지 않았어요"):
            issue_token("https://tls.example", "user", "password", "moodle_mobile_app", opener=opener)


if __name__ == "__main__":
    unittest.main()
