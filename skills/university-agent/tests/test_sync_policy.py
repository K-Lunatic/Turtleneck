"""Cross-process ownership, freshness boundaries and bounded HTTP retry regressions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from features import sync_policy
from providers.moodle_session import MoodleSession, RequestBackoff, _retry_after
from providers.request_metrics import RequestMetrics
from storage.local_db import LocalDatabase
from test_tls_optimization import fixture_pages, replay_opener, run_sync, snapshot
import sync_tls


class SyncPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'school.db'
        self.pages = fixture_pages(2)
        self.instant = datetime(2026, 11, 5, tzinfo=timezone.utc)
        self.clock = patch.object(sync_policy, 'now', side_effect=lambda: self.instant)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        run_sync(sync_tls, self.pages, self.db, '--full', '--metadata-only', recheck=False)
        self.scope = sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture')

    def sync(self, *args, pages=None):
        return run_sync(sync_tls, pages or self.pages, self.db, *args, recheck=False)

    def test_recent_success_skips_login_and_preserves_original_check_times(self):
        previous = sync_tls._saved_sync_state(self.db, 'fixture')
        self.instant += timedelta(minutes=1)
        result = self.sync('--ensure', '--metadata-only')
        self.assertEqual((result['requests'], result['login_calls']), (0, 0))
        self.assertEqual(sync_tls._saved_sync_state(self.db, 'fixture'), previous)

    def test_catalog_boundary_reads_only_lists(self):
        self.instant += timedelta(minutes=5)
        result = self.sync('--ensure', '--metadata-only')
        self.assertEqual(result['requests'], 3)

    def test_interrupted_work_is_not_mistaken_for_recent_success(self):
        with sync_policy.SyncLock(self.db) as guard:
            guard.record(self.scope, failed=True)
        result = self.sync('--ensure', '--metadata-only')
        self.assertEqual(result['requests'], 25)
        with sync_policy.SyncLock(self.db) as guard:
            self.assertFalse(guard.state(self.scope)['failed'])

    def test_academic_boundary_refreshes_hidden_status_without_notice_or_resource_reads(self):
        self.instant += timedelta(minutes=15)
        self.pages['/mod/assign/view.php?id=101'] = '<p>제출 완료</p>'
        result = self.sync('--ensure', '--metadata-only')
        self.assertEqual(result['requests'], 11)
        self.assertEqual(snapshot(self.db)['assignments'][0]['submissionStatus'], 'SUBMITTED')

    def test_notice_and_resource_boundaries_refresh_in_place_changes(self):
        self.instant += timedelta(hours=6)
        self.pages['/mod/ubboard/article.php?id=105&bwid=106'] = (
            '<div class="subject"><h3>수정 공지</h3></div><div class="text_to_html">수정된 본문</div>')
        self.assertEqual(self.sync('--ensure', '--metadata-only')['requests'], 17)
        self.assertTrue(any(row['title'] == '수정 공지' for row in snapshot(self.db)['notices']))
        self.instant += timedelta(hours=18)
        self.pages['/local/ubdoc/worker.php'] = '{"state_code":"100","file_download":"0"}'
        self.assertEqual(self.sync('--ensure', '--metadata-only')['requests'], 25)
        self.assertTrue(all(row['downloadStatus'] == 'PROHIBITED' for row in snapshot(self.db)['resources']))

    def test_metadata_success_does_not_satisfy_original_file_request(self):
        result = self.sync('--ensure', '--resource-id', 'tls-resource-108')
        self.assertEqual(result['requests_by_kind']['file'], 1)
        self.assertEqual(sum(row['downloadStatus'] == 'DOWNLOADED' for row in snapshot(self.db)['resources']), 1)

    def test_force_and_force_academic_bypass_success_age(self):
        self.instant += timedelta(seconds=1)
        self.assertEqual(self.sync('--academic-only')['requests'], 0)
        self.assertEqual(self.sync('--academic-only', '--force')['requests'], 11)
        self.instant += timedelta(seconds=1)
        self.assertEqual(self.sync('--ensure', '--metadata-only', '--force')['requests'], 25)

    def test_other_account_or_origin_cannot_reuse_success(self):
        state = sync_tls._saved_sync_state(self.db, 'fixture')
        from types import SimpleNamespace
        args = SimpleNamespace(force=False, full=False, academic_only=False, resource_id=[], metadata_only=True)
        for scope in (sync_policy.scope_key('https://other.invalid', 'fixture'),
                      sync_policy.scope_key('https://tls.kku.ac.kr', 'other')):
            self.assertFalse(sync_tls._can_reuse(args, state, scope, self.db, 'fixture', self.instant))

    def test_future_and_malformed_stamps_are_not_fresh(self):
        for value in (None, 'bad', self.instant.replace(tzinfo=None).isoformat(),
                      (self.instant + timedelta(seconds=1)).isoformat()):
            self.assertFalse(sync_policy.fresh(value, 300))

    def test_persistent_cooldown_even_force_skips_login_until_expiry(self):
        with sync_policy.SyncLock(self.db) as guard:
            guard.record(self.scope, failed=True, delay=90)
        result = run_sync(sync_tls, self.pages, self.db, '--full', '--metadata-only', recheck=False, allow_failure=True)
        self.assertTrue(result['failed'])
        self.assertEqual((result['requests'], result['login_calls']), (0, 0))
        with sync_policy.SyncLock(self.db) as guard:
            self.assertEqual(guard.remaining(self.scope), 90)
        self.instant += timedelta(seconds=91)
        self.assertEqual(self.sync('--ensure', '--metadata-only')['requests'], 25)
        with sync_policy.SyncLock(self.db) as guard:
            self.assertFalse(guard.state(self.scope)['failed'])

    def test_recent_academic_result_does_not_satisfy_pending_notice_refresh(self):
        self.instant += timedelta(hours=7)
        self.assertEqual(self.sync('--academic-only')['requests'], 11)
        result = self.sync('--ensure', '--metadata-only')
        self.assertEqual(result['requests'], 9)  # lists + notice detail, no repeated academic reads


class ProcessLockTests(unittest.TestCase):
    def test_os_releases_owner_lock_after_process_death(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'school.db'
            code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                    'from features.sync_policy import SyncLock; '
                    'lock=SyncLock(sys.argv[2]); lock.__enter__(); '
                    'print("owned",flush=True); sys.stdin.read()')
            process = subprocess.Popen([sys.executable, '-u', '-c', code, str(ROOT), str(db)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'owned')
                with self.assertRaises(sync_policy.SyncBusy):
                    with sync_policy.SyncLock(db, timeout=0.05):
                        pass
                process.terminate()
                process.wait(timeout=10)
                with sync_policy.SyncLock(db, timeout=1):
                    pass
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=10)

    def test_two_processes_coalesce_a_catalog_check(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'school.db'
            pages = fixture_pages(2)
            run_sync(sync_tls, pages, db, '--full', '--metadata-only', recheck=False)
            with closing(LocalDatabase(db)) as database:
                database.merge_sync_state('fixture', {'catalog_checked_at': '2020-01-01T00:00:00+00:00'})
            code = '''import sys,json,time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_tls_optimization import fixture_pages,run_sync,sync_tls
pages=fixture_pages(2)
body=pages['/local/ubion/user/']
pages['/local/ubion/user/']=lambda request: (time.sleep(0.4),body)[1]
print(json.dumps(run_sync(sync_tls,pages,Path(sys.argv[2]),'--ensure','--metadata-only',recheck=False)))
'''
            processes = [subprocess.Popen([sys.executable, '-c', code, str(ROOT / 'tests'), str(db)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
                         for _ in range(2)]
            results = []
            for process in processes:
                output, error = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, error)
                results.append(json.loads(output))
            self.assertEqual(sorted(row['requests'] for row in results), [0, 3])
            self.assertEqual(sorted(row['login_calls'] for row in results), [0, 1])


class RetryTests(unittest.TestCase):
    def test_cookie_probe_backoff_does_not_fall_through_to_password_login(self):
        from providers import tls_auth
        with patch.object(tls_auth, 'load_username', return_value='fixture'), \
             patch.object(tls_auth, 'load_session'), \
             patch.object(tls_auth, 'MoodleSession') as session, \
             patch.object(tls_auth, 'load') as password, \
             patch.object(tls_auth, 'clear_session') as clear:
            session.return_value.resume.side_effect = RequestBackoff(90)
            with self.assertRaises(RequestBackoff):
                tls_auth.authenticated_session(stored_only=True)
            password.assert_not_called()
            clear.assert_not_called()
            session.return_value.login.assert_not_called()

    def session(self, metrics):
        session = MoodleSession(metrics=metrics)
        session.logged_in = True
        session._request_limiter.gap = 0
        return session

    def test_get_retries_bounded_and_read_only_post_can_recover(self):
        calls = []
        def respond(request):
            calls.append(request.get_method())
            return (503, '', {}) if len(calls) < 3 else 'ok'
        metrics = RequestMetrics()
        with replay_opener({'/read': respond}):
            session = self.session(metrics)
            with patch.object(session._request_limiter, 'pause') as pause:
                self.assertEqual(session.get('/read'), 'ok')
                self.assertEqual(len(calls), 3)
                self.assertTrue(1 <= pause.call_args_list[0].args[0] <= 1.25)
                self.assertTrue(2 <= pause.call_args_list[1].args[0] <= 2.25)
                calls.clear()
                self.assertEqual(session._request('/read', data=b'job=checkState', retry_safe=True)[0], 'ok')
                self.assertEqual(calls, ['POST'] * 3)

    def test_auth_and_write_requests_are_not_replayed(self):
        for status in (401, 403, 503):
            metrics = RequestMetrics()
            with replay_opener({'/write': (status, '', {})}):
                session = self.session(metrics)
                with self.assertRaises((HTTPError, RequestBackoff)):
                    session._request('/write', data=b'fixture')
            self.assertEqual(metrics.snapshot()['requests'], 1)

    def test_long_retry_after_defers_all_workers_without_sleep_or_extra_request(self):
        metrics = RequestMetrics()
        with replay_opener({'/limited': (429, '', {'Retry-After': '90'}), '/other': 'ok'}):
            session = self.session(metrics)
            with patch('providers.moodle_session.time.sleep', side_effect=AssertionError('no long sleep')):
                with self.assertRaises(RequestBackoff) as caught:
                    session.get('/limited')
                self.assertGreaterEqual(caught.exception.seconds, 90)
                with self.assertRaises(RequestBackoff):
                    session.fork().get('/other')
        self.assertEqual(metrics.snapshot()['requests'], 1)

    def test_retry_after_http_date_and_invalid_values(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=90), usegmt=True)
        self.assertTrue(88 <= _retry_after(future) <= 90)
        self.assertEqual(_retry_after('bad'), 0)
        self.assertEqual(_retry_after('120'), 120)

    def test_redirects_and_forks_share_start_spacing(self):
        starts = []
        def respond(request):
            starts.append(time.monotonic())
            return (302, '', {'Location': '/end'}) if request.full_url.endswith('/start') else 'ok'
        with replay_opener({'/start': respond, '/end': respond}):
            session = MoodleSession()
            session.logged_in = True
            session.get('/start')
            session.fork().get('/end')
            session.get('/end')
        self.assertEqual(len(starts), 4)
        self.assertTrue(all(b - a >= 0.24 for a, b in zip(starts, starts[1:])), starts)


if __name__ == '__main__':
    unittest.main()
