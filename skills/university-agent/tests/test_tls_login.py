import io
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.moodle_session import LoginError
from providers.moodle_session import MoodleSession
from providers import credentials
from providers import tls_auth
from providers.forms import FormUnavailable, TLS_CREDENTIALS_FORM, collect_browser
from scripts import sync_tls


class TlsLoginTests(unittest.TestCase):
    def test_tls_session_cache_stays_out_of_the_marker_file(self):
        jar = CookieJar()
        jar.set_cookie(Cookie(version=0, name='MoodleSession', value='fixture-cookie',
                              port=None, port_specified=False, domain='tls.example',
                              domain_specified=True, domain_initial_dot=False, path='/',
                              path_specified=True, secure=True, expires=None, discard=True,
                              comment=None, comment_url=None, rest={}, rfc2109=False))
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'tls-session.json'
            keychain = []

            def security(args, **_kwargs):
                if args[1] == 'add-generic-password':
                    keychain.append(args[-1])
                if args[1] == 'find-generic-password':
                    return SimpleNamespace(stdout=keychain[-1] + '\n')
                return SimpleNamespace(stdout='')

            with patch.object(credentials, 'SESSION_PATH', marker), patch.object(credentials.subprocess, 'run', side_effect=security):
                credentials.save_session('student', jar)
                self.assertNotIn('fixture-cookie', marker.read_text(encoding='utf-8'))
                restored = credentials.load_session('student')
            self.assertEqual(next(iter(restored)).value, 'fixture-cookie')

    def test_cookie_alone_is_not_reported_as_a_successful_login(self):
        session = MoodleSession('https://tls.example')
        session.cookies = [SimpleNamespace(name='MoodleSession')]
        responses = iter([
            ('<form><input name="username"></form>', SimpleNamespace(geturl=lambda: 'https://tls.example/login/index.php')),
            ('<main>redirected</main>', SimpleNamespace(geturl=lambda: 'https://tls.example/')),
        ])

        def request(path, **kwargs):
            if 'data' in kwargs:
                return next(responses)
            if path == '/':
                raise LoginError('login page returned')
            return next(responses)

        with patch.object(session, '_request', side_effect=request):
            with self.assertRaisesRegex(LoginError, 'could not be verified'):
                session.login('student', 'secret')
        self.assertFalse(session.logged_in)

    def test_browser_form_returns_values_through_localhost_only(self):
        opened = {}

        def open_form(url):
            opened["url"] = url

            def submit():
                deadline = time.monotonic() + 1
                while "url" not in opened or not opened["url"]:
                    if time.monotonic() > deadline:
                        return
                    time.sleep(0.01)
                urlopen(opened["url"], timeout=1).read()
                query = parse_qs(urlsplit(url).query)
                body = urlencode({
                    "token": query["token"][0],
                    "username": "student",
                    "password": "secret",
                }).encode()
                urlopen(Request(url, data=body), timeout=1).read()

            threading.Thread(target=submit, daemon=True).start()
            return True

        with patch("providers.forms.webbrowser.open", side_effect=open_form):
            try:
                values = collect_browser(TLS_CREDENTIALS_FORM, timeout=2)
            except PermissionError:
                self.skipTest("이 실행 환경에서는 localhost 소켓을 열 수 없음")

        self.assertEqual(values, {"username": "student", "password": "secret"})
        self.assertTrue(urlsplit(opened["url"]).hostname == "127.0.0.1")

    def test_browser_handoff_without_a_loaded_page_is_not_reported_as_open(self):
        with patch("providers.forms.webbrowser.open", return_value=True):
            try:
                with self.assertRaisesRegex(FormUnavailable, "실제로 표시되지 않았어요"):
                    collect_browser(TLS_CREDENTIALS_FORM, timeout=0.05)
            except PermissionError:
                self.skipTest("이 실행 환경에서는 localhost 소켓을 열 수 없음")

    def test_failed_saved_login_reopens_secure_form_and_saves_only_after_success(self):
        class Session:
            total_calls = 0

            def __init__(self, _base_url):
                self.calls = 0

            def login(self, username, password):
                self.calls += 1
                Session.total_calls += 1
                if Session.total_calls == 1:
                    raise LoginError("invalid")

            def _request(self, path, **kwargs):
                return '<main>dashboard</main>', SimpleNamespace(geturl=lambda: 'https://tls.example/')

        with patch.object(sync_tls, 'resolve', side_effect=[('student', 'old'), ('student', 'new')]) as resolve, \
             patch.object(sync_tls, 'MoodleSession', Session), patch.object(sync_tls, 'save') as save, \
             redirect_stdout(io.StringIO()) as output:
            username, session = sync_tls._login_with_retries('https://tls.example', 'student')

        self.assertEqual(username, 'student')
        self.assertEqual(session.calls, 1)
        self.assertEqual(resolve.call_args_list[0].kwargs, {'force_input': False})
        self.assertEqual(resolve.call_args_list[1].kwargs, {'force_input': True})
        save.assert_called_once_with('student', 'new')
        self.assertIn('(1/3)', output.getvalue())

    def test_valid_saved_session_skips_password_form(self):
        session = object()
        with patch.object(sync_tls, 'resume_saved_session', return_value=('student', session)), \
             patch.object(sync_tls, 'resolve', side_effect=AssertionError('form should not open')):
            username, resumed = sync_tls._login_with_retries('https://tls.example', 'student')
        self.assertEqual((username, resumed), ('student', session))

    def test_rejected_saved_session_is_removed_before_password_fallback(self):
        class Session:
            def restore_cookies(self, _cookies):
                pass

            def resume(self):
                return False

        with patch.object(tls_auth, 'load_username', return_value='student'), \
             patch.object(tls_auth, 'load_session', return_value=CookieJar()), \
             patch.object(tls_auth, 'MoodleSession', return_value=Session()), \
             patch.object(tls_auth, 'clear_session') as clear:
            self.assertIsNone(tls_auth.resume_saved_session('https://tls.example'))
        clear.assert_called_once_with('student')


if __name__ == '__main__':
    unittest.main()
