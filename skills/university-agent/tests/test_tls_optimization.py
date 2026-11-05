"""Deterministic HTTP replay and regressions; never contact TLS or load credentials."""
from contextlib import closing, nullcontext, redirect_stdout, redirect_stderr
from email.message import Message
from io import BytesIO, StringIO
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError
from urllib.parse import urlsplit
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import sync_tls
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import MoodleSession, RequestBackoff
from features import sync_policy
from providers.request_metrics import RequestMetrics, current_metrics, measure_requests
from storage.local_db import LocalDatabase


def fixture_pages(count=8):
    pages = {'/local/ubion/user/': ''.join(
        f'<a href="/course/view.php?id={i}">테스트 과목 {i}</a>' for i in range(1, count + 1))}
    for i in range(1, count + 1):
        number = i * 100
        activities = [('assign', 1, '과제 A'), ('assign', 2, '과제 B'),
                      ('vod', 3, '강의 A'), ('vod', 4, '강의 B'),
                      ('ubboard', 5, '공지사항'), ('ubfile', 8, '자료 A'), ('ubfile', 9, '자료 B')]
        pages[f'/course/view.php?id={i}'] = '<ul><li id="section-1" class="section" aria-label="1주차"><ul>' + ''.join(
            f'<li class="activity"><a href="/mod/{kind}/view.php?id={number + offset}">{title}</a></li>'
            for kind, offset, title in activities) + '</ul></li></ul>'
        for offset in (1, 2):
            pages[f'/mod/assign/view.php?id={number + offset}'] = '<p>마감일: 2026-11-20 23:59</p><p>제출 안 함</p>'
        for offset in (3, 4):
            pages[f'/mod/vod/viewer.php?id={number + offset}'] = (
                '<span class="playtime">10:00</span><script>var is_progress = 50; var is_complete = 0;</script>')
        pages[f'/mod/ubboard/view.php?id={number + 5}'] = ''.join(
            f'<a href="/mod/ubboard/article.php?id={number + 5}&amp;bwid={number + offset}">공지</a>'
            for offset in (6, 7))
        for offset in (6, 7):
            pages[f'/mod/ubboard/article.php?id={number + 5}&bwid={number + offset}'] = (
                '<div class="subject"><h3>테스트 공지</h3></div>'
                '<div class="text_to_html">테스트 공지 본문</div><p>작성일: 2026-11-01 12:00</p>')
        for offset in (8, 9):
            pages[f'/mod/ubfile/view.php?id={number + offset}'] = (
                f'<iframe src="/local/ubdoc/?id={number + offset}&amp;tp=m&amp;pg=ubfile"></iframe>')
            pages[f'/local/ubdoc/download.php?id={number + offset}&tp=m&pg=ubfile'] = b'%PDF-fixture-original'
    pages['/local/ubdoc/worker.php'] = '{"state_code":"100","file_download":"1"}'
    return pages


class FixtureTransport(BaseHandler):
    handler_order = 400

    def __init__(self, pages):
        self.pages = pages

    def https_open(self, request):
        parts = urlsplit(request.full_url)
        key = parts.path + ('?' + parts.query if parts.query else '')
        if key not in self.pages:
            raise AssertionError('Unexpected replay request: ' + key)
        value = self.pages[key]
        if callable(value):
            value = value(request)
        if isinstance(value, Exception):
            raise value
        code, extra = 200, {}
        if isinstance(value, tuple):
            code, value, extra = value
        headers = Message()
        headers['Content-Type'] = 'application/pdf' if isinstance(value, bytes) else 'text/html; charset=utf-8'
        for name, content in extra.items():
            if name in headers:
                headers.replace_header(name, content)
            else:
                headers[name] = content
        response = addinfourl(BytesIO(value if isinstance(value, bytes) else value.encode('utf-8')),
                              headers, request.full_url, code)
        response.msg = 'fixture'
        return response


def replay_opener(pages, session_class=MoodleSession):
    return patch.dict(session_class._build_opener.__globals__,
                      {'build_opener': lambda *handlers: build_opener(*handlers, FixtureTransport(pages))})


def run_sync(module, pages, db_path, *arguments, recheck=True, session_class=MoodleSession, allow_failure=False):
    metrics = RequestMetrics()
    failed = False
    with replay_opener(pages, session_class):
        session = session_class(metrics=metrics)
        session.logged_in = True
        session._request_limiter.gap = 0
        with patch.object(sys, 'argv', ['sync_tls.py', *arguments]), \
             patch.dict(os.environ, {'UNIVERSITY_AGENT_DB': str(db_path), 'UNIVERSITY_AGENT_USER_ID': 'fixture'}), \
             patch.object(module, '_login_with_retries', return_value=('fixture', session)) as login, \
             patch.object(module, 'load_username', return_value='fixture', create=True), \
             (patch.object(sync_policy, 'CATALOG_TTL', 0) if recheck else nullcontext()), \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            try:
                module.main()
            except SystemExit:
                if not allow_failure:
                    raise
                failed = True
    return {**metrics.snapshot(), 'login_calls': login.call_count, 'failed': failed}


def snapshot(path):
    with closing(LocalDatabase(path, read_only=True)) as database:
        result = {}
        for name in ('courses', 'assignments', 'lectures', 'notices', 'resources', 'activities'):
            rows = getattr(database, 'get_' + name)('fixture')
            # Timestamps differ by run; compare every returned data field otherwise.
            result[name] = sorted([{key: value for key, value in row.items()
                                    if key not in ('updatedAt', 'updated_at', 'lastSyncedAt')}
                                   for row in rows], key=lambda row: row['id'])
        return result


def load_baseline(directory):
    modules = {}
    for name in ('moodle_provider', 'sync_tls'):
        spec = importlib.util.spec_from_file_location('tls_baseline_' + name, Path(directory) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    modules['sync_tls'].MoodleTLSProvider = modules['moodle_provider'].MoodleTLSProvider
    return modules


class TLSOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.seed = Path(self.temp.name) / 'seed.db'
        self.pages = fixture_pages()
        run_sync(sync_tls, self.pages, self.seed, '--full', '--metadata-only')

    def copy_seed(self, name='case.db'):
        path = Path(self.temp.name) / name
        shutil.copyfile(self.seed, path)
        return path

    def test_one_changed_course_reuses_pages_and_preserves_other_courses(self):
        pages = dict(self.pages)
        pages['/course/view.php?id=1'] = pages['/course/view.php?id=1'].replace('과제 A', '변경된 과제 A')
        path = self.copy_seed()
        metrics = run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        full_path = self.copy_seed('full.db')
        run_sync(sync_tls, pages, full_path, '--full', '--metadata-only')
        self.assertEqual(snapshot(path), snapshot(full_path))
        self.assertEqual(metrics['requests'], 20)  # 1 list + 8 course pages + 11 detail requests
        self.assertNotIn('file', metrics['requests_by_kind'])

    def test_no_changes_and_status_only_have_same_preflight_cost(self):
        pages = dict(self.pages)
        pages['/mod/assign/view.php?id=101'] = '<p>제출 완료</p>'
        pages['/mod/vod/viewer.php?id=103'] = '<script>var is_progress=100; var is_complete=1;</script>'
        path = self.copy_seed()
        metrics = run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        self.assertEqual(metrics['requests'], 9)
        # Academic-only explicitly refreshes states even without activity-list changes.
        metrics = run_sync(sync_tls, pages, path, '--academic-only', '--force')
        self.assertEqual(metrics['requests'], 41)
        data = snapshot(path)
        self.assertEqual(next(x for x in data['assignments'] if x['id'] == 'tls-assignment-101')['submissionStatus'], 'SUBMITTED')
        self.assertTrue(next(x for x in data['lectures'] if x['id'] == 'tls-lecture-103')['completed'])

    def test_removed_course_prunes_enrollment_without_detail_requests(self):
        pages = dict(self.pages)
        pages['/local/ubion/user/'] = pages['/local/ubion/user/'].replace(
            '<a href="/course/view.php?id=8">테스트 과목 8</a>', '')
        path = self.copy_seed()
        metrics = run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        self.assertEqual(metrics['requests'], 8)
        data = snapshot(path)
        self.assertEqual(len(data['courses']), 7)
        for name in ('assignments', 'lectures', 'notices', 'resources', 'activities'):
            self.assertFalse(any(row['courseId'] == 'tls-course-8' for row in data[name]))

    def test_deleted_activities_removed_only_in_changed_course(self):
        pages = dict(self.pages)
        pages['/course/view.php?id=1'] = ''
        path = self.copy_seed()
        run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        for name in ('assignments', 'lectures', 'notices', 'resources', 'activities'):
            rows = snapshot(path)[name]
            self.assertTrue(rows)
            self.assertFalse(any(row['courseId'] == 'tls-course-1' for row in rows))

    def test_new_course_is_collected_and_existing_data_retained(self):
        path = self.copy_seed()
        metrics = run_sync(sync_tls, fixture_pages(9), path, '--ensure', '--metadata-only')
        self.assertEqual(metrics['requests'], 21)
        self.assertEqual(len(snapshot(path)['assignments']), 18)

    def test_requested_missing_file_scopes_known_course_and_downloads_only_target(self):
        path = self.copy_seed()
        metrics = run_sync(sync_tls, self.pages, path, '--ensure', '--resource-id', 'tls-resource-108')
        self.assertEqual(metrics['requests'], 17)
        self.assertEqual(metrics['requests_by_kind']['file'], 1)
        self.assertEqual(len(snapshot(path)['resources']), 16)
        self.assertEqual(sum(row['downloadStatus'] == 'DOWNLOADED' for row in snapshot(path)['resources']), 1)

    def test_failure_does_not_advance_fingerprints(self):
        pages = dict(self.pages)
        pages['/course/view.php?id=1'] += '<li class="activity">변경</li>'
        pages['/mod/assign/view.php?id=101'] = URLError('fixture failure')
        path = self.copy_seed()
        before = sync_tls._saved_sync_state(path, 'fixture')
        with self.assertRaises(SystemExit):
            run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        self.assertEqual(sync_tls._saved_sync_state(path, 'fixture'), before)
        self.assertEqual(snapshot(path), snapshot(self.seed))

    def test_incompatible_cache_falls_back_to_full_detail_reads(self):
        path = self.copy_seed()
        with closing(LocalDatabase(path)) as database:
            database.merge_sync_state('fixture', {'resource_response_version': 'obsolete'})
        metrics = run_sync(sync_tls, self.pages, path, '--ensure', '--metadata-only')
        self.assertEqual(metrics['requests'], 97)

    def test_corrupt_course_cache_falls_back_to_full_refresh(self):
        result = {'courseIds': ['tls-course-1'], 'fingerprints': {'tls-course-1': 'same'}}
        for courses in ('null', '{}', '[[]]', '[1]', 'invalid'):
            state = {'resource_response_version': MoodleTLSProvider.RESOURCE_RESPONSE_VERSION,
                     'course_ids': courses, 'course_fingerprints': '{"tls-course-1":"same"}'}
            self.assertIsNone(sync_tls._changed_course_ids(state, result))
            self.assertTrue(sync_tls._preflight_changed(state, result, needs_data=False))

    def test_late_failure_preserves_other_courses_and_old_fingerprints(self):
        pages = dict(self.pages)
        pages['/course/view.php?id=1'] = pages['/course/view.php?id=1'].replace('과제 A', '변경된 과제 A')
        pages['/mod/ubboard/view.php?id=105'] = URLError('fixture late failure')
        path = self.copy_seed()
        state = sync_tls._saved_sync_state(path, 'fixture')
        with self.assertRaises(SystemExit):
            run_sync(sync_tls, pages, path, '--ensure', '--metadata-only')
        after = sync_tls._saved_sync_state(path, 'fixture')
        for key in ('course_ids', 'course_fingerprints', 'catalog_checked_at', 'notice_course_checks', 'resource_course_checks'):
            self.assertEqual(after[key], state[key])
        for name, rows in snapshot(path).items():
            if name == 'courses':
                continue
            self.assertEqual([row for row in rows if row['courseId'] != 'tls-course-1'],
                             [row for row in snapshot(self.seed)[name] if row['courseId'] != 'tls-course-1'])


class RequestMetricsTests(unittest.TestCase):
    def test_metrics_cli_captures_sessions_and_emits_counters_even_on_failure(self):
        def fail_after_request():
            session = MoodleSession()
            session.logged_in = True
            session.get('/fixture')
            self.assertIs(session.fork().metrics, session.metrics)
            raise RuntimeError('fixture failure')

        output = StringIO()
        with replay_opener({'/fixture': 'body'}), patch.object(sys, 'argv', ['sync_tls.py', '--metrics']), \
             patch.object(sync_tls, '_main', side_effect=fail_after_request), redirect_stderr(output):
            with self.assertRaises(RuntimeError):
                sync_tls.main()
        result = json.loads(output.getvalue().removeprefix('TLS_METRICS '))
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['response_body_bytes'], 4)
        self.assertIsNone(current_metrics.get())

    def test_redirect_compression_errors_and_forks_count_real_http_boundaries(self):
        import gzip
        body = gzip.compress(b'fixture body' * 50)
        pages = {'/start': (302, '', {'Location': '/end'}),
                 '/end': (200, body, {'Content-Encoding': 'gzip', 'Content-Type': 'text/html'}),
                 '/unchanged': (304, '', {}), '/failed': (429, '', {}),
                 '/broken': URLError('offline')}
        metrics = RequestMetrics()
        with replay_opener(pages):
            session = MoodleSession(metrics=metrics)
            session.logged_in = True
            session._request_limiter.gap = 0
            self.assertEqual(session.get('/start'), 'fixture body' * 50)
            self.assertIsNone(session.fork().get_bytes('/unchanged')[0])
            session._request_limiter.pause = lambda *args, **kwargs: None
            with self.assertRaises(RequestBackoff):
                session.get('/failed')
            with self.assertRaises(RequestBackoff):
                session.get('/broken')
        result = metrics.snapshot()
        self.assertEqual(result['requests'], 9)
        self.assertEqual(result['response_body_bytes'], len(body))
        self.assertEqual(result['statuses'], {'302': 1, '200': 1, '304': 1, '429': 3, 'transport_error': 3})
        self.assertEqual(metrics.active, 0)


if __name__ == '__main__':
    unittest.main()
