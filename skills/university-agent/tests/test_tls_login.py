import io
import os
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
    def setUp(self):
        tls_auth.clear_process_session_cache()

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
                    self.assertNotIn('fixture-cookie', args)
                    keychain.append(_kwargs['input'].rstrip('\n'))
                if args[1] == 'find-generic-password':
                    return SimpleNamespace(stdout=keychain[-1] + '\n')
                return SimpleNamespace(stdout='')

            with patch.object(credentials, 'SESSION_PATH', marker), \
                 patch.object(credentials, '_save_keychain_secret', side_effect=lambda service, alias, secret: keychain.append(secret)), \
                 patch.object(credentials, '_read_keychain_secret', side_effect=lambda service, alias: keychain[-1]), \
                 patch.object(credentials.subprocess, 'run', side_effect=security):
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

        self.assertEqual(values, {"alias": "", "username": "student", "password": "secret"})
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
        self.assertEqual(resolve.call_args_list[0].kwargs['force_input'], False)
        self.assertEqual(resolve.call_args_list[0].kwargs['site'], 'tls.example')
        self.assertTrue(callable(resolve.call_args_list[0].kwargs['submit_check']))
        self.assertEqual(resolve.call_args_list[1].kwargs['force_input'], True)
        self.assertEqual(resolve.call_args_list[1].kwargs['site'], 'tls.example')
        self.assertTrue(callable(resolve.call_args_list[1].kwargs['submit_check']))
        save.assert_called_once_with('student', 'new', 'default', 'tls.example')
        self.assertIn('(1/3)', output.getvalue())

    def test_valid_saved_session_skips_password_form(self):
        session = object()
        with patch.object(sync_tls, 'resume_saved_session', return_value=('student', session)), \
             patch.object(sync_tls, 'resolve', side_effect=AssertionError('form should not open')):
            username, resumed = sync_tls._login_with_retries('https://tls.example', 'student')
        self.assertEqual((username, resumed), ('student', session))

    def test_missing_stored_password_does_not_reopen_form_automatically(self):
        with patch.object(sync_tls, 'resume_saved_session', return_value=None), \
             patch.object(sync_tls, 'load', side_effect=ValueError('missing')), \
             patch.object(sync_tls, 'load_username', return_value='student'), \
             patch.object(sync_tls, 'resolve', side_effect=AssertionError('form should require explicit reconnect')):
            with self.assertRaisesRegex(RuntimeError, '연결 명령으로 한 번만'):
                sync_tls._login_with_retries('https://tls.example', 'student')

    def test_empty_stored_password_does_not_send_login_request(self):
        with patch.object(sync_tls, 'resume_saved_session', return_value=None), \
             patch.object(sync_tls, 'load', return_value=('student', '')), \
             patch.object(sync_tls, 'load_username', return_value='student'), \
             patch.object(sync_tls, 'MoodleSession') as session:
            with self.assertRaisesRegex(RuntimeError, '연결 명령으로 한 번만'):
                sync_tls._login_with_retries('https://tls.example', 'student', stored_only=True)
        session.assert_not_called()

    def test_shared_authenticated_session_rejects_empty_stored_password_without_network_login(self):
        with patch.object(tls_auth, 'resume_saved_session', return_value=None), \
             patch.object(tls_auth, 'load', return_value=('student', '')), \
             patch.object(tls_auth, 'MoodleSession') as session:
            with self.assertRaisesRegex(RuntimeError, '연결 명령으로 한 번만'):
                tls_auth.authenticated_session('https://tls.example', stored_only=True)
        session.assert_not_called()

    def test_shared_authenticated_session_does_not_reopen_form_when_saved_secret_is_missing(self):
        with patch.object(tls_auth, 'resume_saved_session', return_value=None), \
             patch.object(tls_auth, 'load', side_effect=ValueError('missing')), \
             patch.object(tls_auth, 'resolve_profile') as form, \
             patch.object(tls_auth, 'MoodleSession') as session:
            with self.assertRaisesRegex(RuntimeError, '연결 명령으로 한 번만 다시 로그인'):
                tls_auth.authenticated_session('https://tls.example')
        form.assert_not_called()
        session.assert_not_called()

    def test_shared_authenticated_session_reports_session_cache_failure_without_secret(self):
        class Session:
            cookies = object()

            def __init__(self, _base_url):
                pass

            def login(self, _username, _password):
                pass

        with patch.object(tls_auth, 'resume_saved_session', return_value=None), \
             patch.object(tls_auth, 'load', return_value=('student', 'secret')), \
             patch.object(tls_auth, 'MoodleSession', Session), \
             patch.object(tls_auth, 'save'), \
             patch.object(tls_auth, 'save_session', side_effect=RuntimeError('keychain unavailable')), \
             redirect_stdout(io.StringIO()) as output:
            username, _session = tls_auth.authenticated_session('https://tls.example')

        self.assertEqual(username, 'student')
        self.assertIn('보호 저장소에 세션을 보관하지 못했어요', output.getvalue())
        self.assertNotIn('secret', output.getvalue())

    def test_stored_only_relogin_does_not_rewrite_password(self):
        class Session:
            cookies = object()

            def __init__(self, _base_url):
                pass

            def login(self, _username, _password):
                pass

        with patch.object(tls_auth, 'resume_saved_session', return_value=None), \
             patch.object(tls_auth, 'load', return_value=('student', 'secret')), \
             patch.object(tls_auth, 'MoodleSession', Session), \
             patch.object(tls_auth, 'save') as save, \
             patch.object(tls_auth, 'save_session'):
            username, _session = tls_auth.authenticated_session('https://tls.example', stored_only=True)
        self.assertEqual(username, 'student')
        save.assert_not_called()

    def test_authenticated_session_reuses_one_process_session_without_reopening_login(self):
        class Session:
            logged_in = True
            cookies = object()

            def __init__(self, _base_url):
                self.login_calls = 0

            def login(self, _username, _password):
                self.login_calls += 1

        with patch.object(tls_auth, 'resume_saved_session', return_value=None) as resume, \
             patch.object(tls_auth, 'load', return_value=('student', 'secret')), \
             patch.object(tls_auth, 'MoodleSession', side_effect=Session) as session_type, \
             patch.object(tls_auth, 'save'), patch.object(tls_auth, 'save_session'):
            first = tls_auth.authenticated_session('https://tls.example')
            second = tls_auth.authenticated_session('https://tls.example')
        self.assertIs(first[1], second[1])
        self.assertEqual(session_type.call_count, 1)
        self.assertEqual(first[1].login_calls, 1)
        resume.assert_called_once()

    def test_authenticated_session_serializes_separate_process_login(self):
        session = object()
        with patch.object(tls_auth, 'SyncLock') as lock, \
             patch.object(tls_auth, 'load_active_alias', return_value='default'), \
             patch.object(tls_auth, 'profile_db_path', return_value=Path('/tmp/turtleneck-auth.db')), \
             patch.object(tls_auth, '_authenticated_session_unlocked', return_value=('student', session)) as login:
            lock.return_value.__enter__.return_value = lock.return_value
            result = tls_auth.authenticated_session('https://tls.example')
        self.assertEqual(result, ('student', session))
        lock.assert_called_once()
        login.assert_called_once_with('https://tls.example', None, stored_only=False,
                                      profile_alias='default', allow_prompt=False)

    def test_shared_credential_resolver_does_not_reopen_form_for_empty_secret(self):
        with patch.object(credentials, 'load', side_effect=ValueError('empty')), \
             patch.object(credentials, 'load_username', return_value='student'), \
             patch.object(credentials, 'collect_secure') as form:
            with self.assertRaisesRegex(FormUnavailable, '연결 명령으로 한 번만'):
                credentials.resolve_profile(site='tls.example')
        form.assert_not_called()

    def test_rejected_stored_credentials_explain_reconnection_without_secret(self):
        class Session:
            def __init__(self, _base_url):
                pass

            def login(self, _username, _password):
                raise LoginError('Moodle errorcode=3')

        with patch.object(sync_tls, 'resume_saved_session', return_value=None), \
             patch.object(sync_tls, 'load', return_value=('student', 'secret')), \
             patch.object(sync_tls, 'MoodleSession', Session):
            with self.assertRaisesRegex(RuntimeError, '연결 화면을 다시 열어 로그인') as caught:
                sync_tls._login_with_retries('https://tls.example', stored_only=True)
        self.assertNotIn('secret', str(caught.exception))

    def test_session_store_failure_is_reported_without_exposing_secrets(self):
        class Session:
            cookies = object()

            def __init__(self, _base_url):
                pass

            def login(self, username, password):
                self.username = username

        with patch.object(sync_tls, 'resume_saved_session', return_value=None), \
             patch.object(sync_tls, 'resolve', return_value=('student', 'secret')), \
             patch.object(sync_tls, 'MoodleSession', Session), \
             patch.object(sync_tls, 'save'), \
             patch.object(sync_tls, 'save_session', side_effect=RuntimeError('keychain unavailable')), \
             redirect_stdout(io.StringIO()) as output:
            username, _session = sync_tls._login_with_retries('https://tls.example', 'student')

        self.assertEqual(username, 'student')
        message = output.getvalue()
        self.assertIn('보호 저장소에 세션을 보관하지 못했어요', message)
        self.assertNotIn('secret', message)

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
        clear.assert_called_once_with('student', 'default', 'tls.example')

    def test_missing_keychain_session_is_treated_as_expired(self):
        with patch.object(tls_auth, 'load_username', return_value='student'), \
             patch.object(tls_auth, 'load_session', side_effect=credentials.subprocess.CalledProcessError(44, 'security')):
            self.assertIsNone(tls_auth.resume_saved_session('https://tls.example'))

    @unittest.skipIf(os.name == 'nt', 'Windows sessions use DPAPI and need no Keychain deletion')
    def test_expired_session_cleanup_uses_shared_keychain_delete_path(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'tls-session.json'
            marker.write_text('{"activeAlias":"default","profiles":{"default":{"username":"student"}}}', encoding='utf-8')
            with patch.object(credentials, 'SESSION_PATH', marker), \
                 patch.object(credentials, '_delete_keychain_secret') as delete_secret, \
                 patch.object(credentials.subprocess, 'run') as run:
                credentials.clear_session('student')
            delete_secret.assert_called_once_with(credentials.SESSION_SERVICE, 'default')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
