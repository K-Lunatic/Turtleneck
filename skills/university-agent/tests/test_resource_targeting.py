"""Selected resource detail reads must preserve other records and freshness scopes."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import URLError

from test_tls_optimization import fixture_pages, run_sync, snapshot, replay_opener, sync_tls
from features import sync_policy
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import MoodleSession


class ResourceTargetingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'school.db'
        self.pages = fixture_pages(2)
        self.instant = datetime(2026, 11, 6, tzinfo=timezone.utc)
        clock = patch.object(sync_policy, 'now', side_effect=lambda: self.instant)
        clock.start()
        self.addCleanup(clock.stop)
        run_sync(sync_tls, self.pages, self.db, '--full', '--metadata-only', recheck=False)
        self.instant += timedelta(minutes=1)

    def sync(self, *extra, pages=None, allow_failure=False):
        return run_sync(sync_tls, pages or self.pages, self.db, '--ensure', '--resource-id', 'tls-resource-108',
                        *extra, recheck=False, allow_failure=allow_failure)

    def state(self):
        return sync_tls._saved_sync_state(self.db, 'fixture')

    def test_selected_detail_only_and_unselected_records_preserved(self):
        before, state = snapshot(self.db), self.state()
        result = self.sync()
        self.assertEqual(result['requests'], 9)  # 3 lists + 3 notice + 2 detail + 1 file
        self.assertEqual(result['requests_by_kind']['file'], 1)
        after = snapshot(self.db)
        self.assertEqual([x for x in before['resources'] if x['id'] != 'tls-resource-108'],
                         [x for x in after['resources'] if x['id'] != 'tls-resource-108'])
        self.assertEqual(self.state()['resource_course_checks'], state['resource_course_checks'])
        self.assertEqual(self.state()['resource_checked_at'], state['resource_checked_at'])
        self.assertIn('tls-resource-108', json.loads(self.state()['resource_item_checks']))

    def test_unselected_error_is_not_requested_but_target_error_is_preserved(self):
        self.pages['/mod/ubfile/view.php?id=109'] = URLError('unselected must not be read')
        self.assertFalse(self.sync()['failed'])
        before = snapshot(self.db)['resources']
        self.instant += timedelta(seconds=1)
        self.pages['/mod/ubfile/view.php?id=108'] = URLError('selected unavailable')
        with patch('providers.moodle_session._RequestLimiter.pause'):
            result = self.sync(allow_failure=True)
        self.assertTrue(result['failed'])
        self.assertEqual(snapshot(self.db)['resources'], before)

    def test_notice_restriction_is_rechecked_before_download(self):
        self.pages['/mod/ubboard/article.php?id=105&bwid=106'] = (
            '<div class="subject"><h3>자료 안내</h3></div>'
            '<div class="text_to_html">모든 자료 다운로드 금지</div>')
        result = self.sync()
        target = next(x for x in snapshot(self.db)['resources'] if x['id'] == 'tls-resource-108')
        self.assertEqual(target['downloadStatus'], 'PROHIBITED')
        self.assertEqual(result['requests_by_kind'].get('file', 0), 0)

    def test_expired_or_forced_course_keeps_full_detail_scan(self):
        self.assertEqual(self.sync('--force')['requests'], 26)  # 25 metadata + 1 file
        self.instant += timedelta(days=1)
        self.assertEqual(self.sync()['requests'], 26)

    def test_changed_course_removes_missing_resource(self):
        self.pages['/course/view.php?id=1'] = self.pages['/course/view.php?id=1'].replace(
            '<li class="activity"><a href="/mod/ubfile/view.php?id=109">자료 B</a></li>', '')
        self.sync()
        self.assertNotIn('tls-resource-109', {x['id'] for x in snapshot(self.db)['resources']})

    def test_mixed_full_and_partial_courses_do_not_lose_resources(self):
        self.pages['/course/view.php?id=2'] = self.pages['/course/view.php?id=2'].replace('과제 A', '변경 과제 A')
        result = self.sync()
        self.assertEqual(result['requests'], 20)  # lists 3 + academic 4 + notices 6 + details 6 + file 1
        self.assertEqual(len(snapshot(self.db)['resources']), 4)
        checks = json.loads(self.state()['resource_course_checks'])
        self.assertNotEqual(checks['tls-course-1'], checks['tls-course-2'])

    def test_new_or_unknown_id_uses_full_fallback(self):
        result = self.sync('--resource-id', 'tls-resource-unknown')
        self.assertEqual(result['requests'], 18)  # 3 lists + 6 notice + 8 detail + 1 file
        self.assertEqual(len(snapshot(self.db)['resources']), 4)

    def test_item_check_coalesces_same_file_but_not_another_file(self):
        started = self.instant
        self.instant += timedelta(seconds=1)
        self.sync()
        args = SimpleNamespace(force=False, full=False, academic_only=False,
                               resource_id=['tls-resource-108'], metadata_only=False)
        scope = sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture')
        self.assertTrue(sync_tls._can_reuse(args, self.state(), scope, self.db, 'fixture', started))
        args.resource_id = ['tls-resource-109']
        self.assertFalse(sync_tls._can_reuse(args, self.state(), scope, self.db, 'fixture', started))

    def test_provider_filter_can_return_only_target_or_no_items(self):
        with replay_opener(self.pages):
            session = MoodleSession()
            session.logged_in = True
            session._request_limiter.gap = 0
            provider = MoodleTLSProvider(session)
            self.assertEqual(provider.get_resources('fixture', resource_ids=set(), detail_course_ids=set()), [])
            rows = provider.get_resources('fixture', resource_ids={'tls-resource-109'},
                                          detail_course_ids=set(), download_new_files=False)
            self.assertEqual([x['id'] for x in rows], ['tls-resource-109'])


if __name__ == '__main__':
    unittest.main()
