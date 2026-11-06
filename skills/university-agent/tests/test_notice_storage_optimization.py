"""Notice-body reuse and NULL-safe storage writes retain freshness and cleanup."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_tls_optimization import fixture_pages, run_sync, snapshot, sync_tls
from features import sync_policy
from providers.moodle_provider import notice_listing_fingerprints
from storage.local_db import LocalDatabase


def notice_fixture(courses=2, articles=2):
    pages = fixture_pages(courses)
    identifiers = [106, 107] + list(range(20000, 20000 + articles - 2))
    rows = []
    for index, identifier in enumerate(identifiers):
        rows.append(f'<tr><td class="title"><a href="/mod/ubboard/article.php?id=105&amp;bwid={identifier}">공지 {index}</a></td>'
                    '<td class="date">2026-11-01</td><td class="hit">0</td></tr>')
        pages[f'/mod/ubboard/article.php?id=105&bwid={identifier}'] = (
            f'<div class="subject"><h3>공지 {index}</h3></div><div class="text_to_html">본문 {index}</div>')
    pages['/mod/ubboard/view.php?id=105'] = '<table>' + ''.join(rows) + '</table>'
    return pages


def storage_payload(count=3):
    return {
        'courses': [{'id': 'c', 'name': '과목'}],
        'assignments': [{'id': f'a{i}', 'courseId': 'c', 'title': f'과제 {i}', 'dueAt': None,
                         'submissionStatus': 'NOT_SUBMITTED'} for i in range(count)],
        'lectures': [{'id': f'l{i}', 'courseId': 'c', 'title': f'강의 {i}', 'durationSeconds': 600,
                      'watchedSeconds': 300, 'watchProgress': 50, 'completed': False} for i in range(count)],
        'notices': [{'id': f'n{i}', 'courseId': 'c', 'title': f'공지 {i}', 'content': '본문',
                     'publishedAt': '2026-11-01T00:00:00+09:00'} for i in range(count)],
        'resources': [{'id': f'r{i}', 'courseId': 'c', 'title': f'자료 {i}', 'fileName': f'{i}.pdf',
                       'extension': 'pdf', 'remotePath': f'/resource/{i}'} for i in range(count)],
        'activities': [{'id': f't{i}', 'courseId': 'c', 'externalId': str(i), 'type': 'resource',
                        'title': f'활동 {i}', 'url': f'/resource/{i}'} for i in range(count)],
    }


def write_payload(db, data, *, stamp='2026-11-06T00:00:00+00:00'):
    db.upsert_tls_snapshot('fixture', data['courses'], data['assignments'], data['lectures'], 'User', None,
                           now=stamp, notices=data['notices'], resources=data['resources'], activities=data['activities'])


class NoticeOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'school.db'
        self.pages = notice_fixture()
        self.instant = datetime(2026, 11, 6, tzinfo=timezone.utc)
        clock = patch.object(sync_policy, 'now', side_effect=lambda: self.instant)
        clock.start()
        self.addCleanup(clock.stop)
        run_sync(sync_tls, self.pages, self.db, '--full', '--metadata-only', recheck=False)
        self.original_checks = self.state()
        self.instant += timedelta(minutes=1)

    def state(self):
        return sync_tls._saved_sync_state(self.db, 'fixture')

    def changed_course(self, suffix='변경'):
        self.pages['/course/view.php?id=1'] = self.pages['/course/view.php?id=1'].replace('과제 A', '과제 A ' + suffix)

    def sync(self, *args, allow_failure=False):
        return run_sync(sync_tls, self.pages, self.db, '--ensure', '--metadata-only', *args,
                        recheck=True, allow_failure=allow_failure)

    def test_unchanged_notice_rows_reuse_bodies_without_advancing_checks(self):
        self.changed_course()
        before = snapshot(self.db)['notices']
        self.assertEqual(self.sync()['requests'], 12)
        self.assertEqual(snapshot(self.db)['notices'], before)
        for key in ('notice_course_checks', 'notice_checked_at', 'notice_detail_checks'):
            self.assertEqual(self.state()[key], self.original_checks[key])

    def test_new_and_edited_notice_rows_are_fetched(self):
        self.changed_course()
        self.pages['/mod/ubboard/view.php?id=105'] = self.pages['/mod/ubboard/view.php?id=105'].replace('공지 0', '수정 공지')
        self.pages['/mod/ubboard/article.php?id=105&bwid=106'] = '<div class="subject"><h3>수정 공지</h3></div>'
        self.assertEqual(self.sync()['requests'], 13)
        self.assertTrue(any(x['title'] == '수정 공지' for x in snapshot(self.db)['notices']))
        self.instant += timedelta(minutes=1)
        self.changed_course('다음 변경')
        self.pages['/mod/ubboard/view.php?id=105'] += '<table><tr><td><a href="/mod/ubboard/article.php?id=105&bwid=20000">새 글</a></td></tr></table>'
        self.pages['/mod/ubboard/article.php?id=105&bwid=20000'] = '<div class="subject"><h3>새 공지</h3></div>'
        self.assertEqual(self.sync()['requests'], 13)
        self.assertIn('tls-notice-20000', {x['id'] for x in snapshot(self.db)['notices']})

    def test_body_only_edit_is_rechecked_at_original_six_hour_boundary(self):
        self.pages['/mod/ubboard/article.php?id=105&bwid=106'] = '<div class="subject"><h3>본문만 수정</h3></div>'
        self.instant += timedelta(hours=5)
        self.changed_course()
        self.sync()
        self.assertFalse(any(x['title'] == '본문만 수정' for x in snapshot(self.db)['notices']))
        self.instant = datetime(2026, 11, 6, 6, tzinfo=timezone.utc)
        self.sync()
        self.assertTrue(any(x['title'] == '본문만 수정' for x in snapshot(self.db)['notices']))

    def test_force_and_file_permission_checks_always_fetch_bodies(self):
        self.assertEqual(self.sync('--force')['requests'], 25)
        self.instant += timedelta(seconds=1)
        self.assertEqual(self.sync('--resource-id', 'tls-resource-108')['requests'], 8)

    def test_read_counter_does_not_invalidate_but_visible_date_does(self):
        html = self.pages['/mod/ubboard/view.php?id=105']
        self.assertEqual(notice_listing_fingerprints(html),
                         notice_listing_fingerprints(html.replace('class="hit">0', 'class="hit">99')))
        self.assertNotEqual(notice_listing_fingerprints(html),
                            notice_listing_fingerprints(html.replace('2026-11-01', '2026-11-02')))

    def test_real_tls_shared_cell_class_uses_headers_to_ignore_view_counts(self):
        html = ('<table><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th><th>조회수</th></tr>'
                '<tr><td class="tcenter">1</td><td><a href="/mod/ubboard/article.php?id=105&bwid=106">공지</a></td>'
                '<td class="tcenter">작성자</td><td class="tcenter">2026-11-01</td><td class="tcenter">2</td></tr></table>')
        self.assertEqual(notice_listing_fingerprints(html), notice_listing_fingerprints(html.replace('>2</td>', '>99</td>')))
        self.assertNotEqual(notice_listing_fingerprints(html), notice_listing_fingerprints(html.replace('2026-11-01', '2026-11-02')))

    def test_unrecognized_markup_and_missing_cache_use_full_fallback(self):
        self.changed_course()
        self.pages['/mod/ubboard/view.php?id=105'] = self.pages['/mod/ubboard/view.php?id=105'].replace('<tr>', '<div>').replace('</tr>', '</div>')
        self.assertEqual(self.sync()['requests'], 14)
        self.instant += timedelta(seconds=1)
        self.changed_course('새 변경')
        database = LocalDatabase(self.db)
        try:
            with database.connection as db:
                db.execute("UPDATE sync_state SET state_value='[]' WHERE user_id='fixture' AND state_key='notice_detail_checks'")
        finally:
            database.close()
        self.assertEqual(self.sync()['requests'], 14)

    def test_removed_notice_is_pruned_and_other_course_preserved(self):
        self.changed_course()
        self.pages['/mod/ubboard/view.php?id=105'] = '<table><tr><td><a href="/mod/ubboard/article.php?id=105&bwid=106">공지 0</a></td></tr></table>'
        self.sync()
        ids = {x['id'] for x in snapshot(self.db)['notices']}
        self.assertNotIn('tls-notice-107', ids)
        self.assertIn('tls-notice-206', ids)
        self.assertNotIn('tls-notice-107', json.loads(self.state()['notice_detail_checks']))

    def test_failed_notice_read_preserves_cache_and_previous_data(self):
        from urllib.error import URLError
        self.changed_course()
        self.pages['/mod/ubboard/view.php?id=105'] = self.pages['/mod/ubboard/view.php?id=105'].replace('공지 0', '수정 공지')
        self.pages['/mod/ubboard/article.php?id=105&bwid=106'] = URLError('fixture failure')
        before = snapshot(self.db)['notices']
        with patch('providers.moodle_session._RequestLimiter.pause'):
            self.assertTrue(self.sync(allow_failure=True)['failed'])
        self.assertEqual(snapshot(self.db)['notices'], before)
        self.assertEqual(self.state()['notice_detail_checks'], self.original_checks['notice_detail_checks'])

    def test_other_course_cache_and_future_stamps_are_not_reused(self):
        state = json.loads(self.state()['notice_detail_checks'])
        state['tls-notice-106']['checked_at'] = (self.instant + timedelta(days=1)).isoformat()
        db = LocalDatabase(self.db)
        try:
            db.merge_sync_state('fixture', {'notice_detail_checks': json.dumps(state)})
        finally:
            db.close()
        self.changed_course()
        self.assertEqual(self.sync()['requests'], 13)


class StorageOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = LocalDatabase(Path(self.temp.name) / 'school.db')
        self.addCleanup(self.db.close)
        self.data = storage_payload()
        write_payload(self.db, self.data)

    def changed_rows(self, call):
        before = self.db.connection.total_changes
        call()
        return self.db.connection.total_changes - before

    def test_unchanged_snapshot_writes_only_user_sync_time(self):
        self.assertEqual(self.changed_rows(lambda: write_payload(self.db, self.data, stamp='later')), 1)
        self.assertEqual(self.db.get_user('fixture')['lastSyncedAt'], 'later')
        for table in ('courses', 'assignments', 'assignment_submissions', 'lectures', 'lecture_progress', 'notices', 'resources', 'course_activities'):
            self.assertEqual(self.db.connection.execute(f'SELECT COUNT(*) FROM {table} WHERE updated_at=?', ('later',)).fetchone()[0], 0)

    def test_single_status_and_null_transitions_write_only_changed_rows(self):
        data = deepcopy(self.data)
        data['assignments'][0].update(submissionStatus='SUBMITTED', description='설명')
        self.assertEqual(self.changed_rows(lambda: write_payload(self.db, data)), 3)
        data['assignments'][0]['description'] = None
        self.assertEqual(self.changed_rows(lambda: write_payload(self.db, data)), 2)
        self.assertIsNone(self.db.get_assignments('fixture')[0]['description'])

    def test_resource_permission_change_is_not_skipped(self):
        data = deepcopy(self.data)
        data['resources'][0].update(downloadStatus='PROHIBITED', downloadReason='다운로드 금지')
        self.assertEqual(self.changed_rows(lambda: write_payload(self.db, data)), 2)
        self.assertEqual(self.db.get_resources('fixture')[0]['downloadStatus'], 'PROHIBITED')

    def test_state_merge_preserves_unrelated_keys_and_removes_only_replaced_keys(self):
        self.db.save_sync_state('fixture', {'a': '1', 'b': '2'})
        self.assertEqual(self.changed_rows(lambda: self.db.merge_sync_state('fixture', {'a': '1'})), 0)
        self.assertEqual(self.changed_rows(lambda: self.db.merge_sync_state('fixture', {'a': '3'})), 1)
        self.assertEqual(self.db.get_sync_state('fixture'), {'a': '3', 'b': '2'})
        self.assertEqual(self.changed_rows(lambda: self.db.save_sync_state('fixture', {'a': '3'})), 1)
        self.assertEqual(self.db.get_sync_state('fixture'), {'a': '3'})

    def test_cleanup_and_other_user_records_are_preserved(self):
        self.db.upsert_tls_snapshot('other', self.data['courses'], self.data['assignments'], self.data['lectures'], 'Other', None)
        data = deepcopy(self.data)
        data['assignments'] = []
        data['lectures'] = []
        data['notices'] = []
        data['resources'] = []
        data['activities'] = []
        write_payload(self.db, data)
        self.assertEqual(self.db.get_assignments('fixture'), [])
        self.assertEqual(len(self.db.get_assignments('other')), 3)
        self.assertEqual(self.db.get_lectures('fixture'), [])
        self.assertEqual(self.db.get_resources('fixture'), [])
        self.assertEqual(self.db.connection.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
