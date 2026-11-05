#!/usr/bin/env python3
"""Offline comparison of stages 0-2 and 0-5, with explicit freshness scenarios."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT), str(ROOT / 'scripts')]
from test_tls_optimization import fixture_pages, run_sync, snapshot, load_baseline, replay_opener
from features import sync_policy
from providers.moodle_session import MoodleSession
from providers.request_metrics import RequestMetrics
import sync_tls


def load_stage012(directory):
    with zipfile.ZipFile(REPO / 'tls-optimization-results/stage012_sources.zip') as archive:
        for name in ('moodle_provider.py', 'sync_tls.py', 'moodle_session.py'):
            (Path(directory) / name).write_bytes(archive.read(name))
    modules = load_baseline(directory)
    spec = importlib.util.spec_from_file_location('stage012_session', Path(directory) / 'moodle_session.py')
    session = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(session)
    modules['session'] = session.MoodleSession
    return modules


def totals(runs):
    return {key: sum(row[key] for row in runs) for key in
            ('requests', 'response_body_bytes', 'login_calls', 'elapsed_seconds')}


def rate_comparison(before_session):
    rows = {}
    for label, session_class in (('stage012', before_session), ('stage012345', MoodleSession)):
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        with patch('time.monotonic', side_effect=lambda: clock[0]), patch('time.sleep', side_effect=sleep), \
             replay_opener({'/start': (302, '', {'Location': '/end'}), '/end': 'ok'}, session_class):
            metrics = RequestMetrics()
            session = session_class(metrics=metrics)
            session.logged_in = True
            for _ in range(6):
                session.get('/start')
            rows[label] = metrics.snapshot()
    assert rows['stage012']['requests'] == rows['stage012345']['requests'] == 12
    assert rows['stage012345']['peak_requests_per_second'] <= 4
    return {'method': 'virtual clock, six GETs each followed by one redirect; not live throughput', **rows}


def main():
    start = datetime(2026, 11, 5, tzinfo=timezone.utc)
    report = {'measurement': 'offline HTTP replay', 'baseline': 'stages 0-1-2',
              'after': 'stages 0-1-2-3-4-5', 'courses': 8, 'results': []}
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        baseline = load_stage012(folder)
        seed = folder / 'seed.db'
        original = fixture_pages()
        with patch.object(sync_policy, 'now', return_value=start):
            run_sync(sync_tls, original, seed, '--full', '--metadata-only', recheck=False)
        cases = [
            ('ten_recent_calls', 60, 10, ['--ensure', '--metadata-only']),
            ('catalog_due', 300, 1, ['--ensure', '--metadata-only']),
            ('one_course_changed_after_catalog_age', 300, 1, ['--ensure', '--metadata-only']),
            ('status_only_default', 900, 1, ['--ensure', '--metadata-only']),
            ('status_fresh_equivalent', 900, 1, ['--ensure', '--metadata-only']),
            ('notice_fresh_equivalent', 21600, 1, ['--ensure', '--metadata-only']),
            ('daily_all_scopes_due', 86400, 1, ['--ensure', '--metadata-only']),
            ('requested_file', 60, 1, ['--ensure', '--resource-id', 'tls-resource-108']),
            ('three_calls_during_retry_after', 60, 3, ['--academic-only']),
        ]
        for name, age, repeats, arguments in cases:
            pages = dict(original)
            if name == 'one_course_changed_after_catalog_age':
                pages['/course/view.php?id=1'] = pages['/course/view.php?id=1'].replace('과제 A', '변경된 과제 A')
            if name.startswith('status_'):
                pages['/mod/assign/view.php?id=101'] = '<p>제출 완료</p>'
            if name == 'notice_fresh_equivalent':
                pages['/mod/ubboard/article.php?id=105&bwid=106'] = (
                    '<div class="subject"><h3>수정 공지</h3></div><div class="text_to_html">수정</div>')
            if name == 'three_calls_during_retry_after':
                pages['/local/ubion/user/'] = (429, '', {'Retry-After': '90'})
            row, data = {'scenario': name, 'seconds_after_success': age, 'calls': repeats}, {}
            for label, module, session_class in (('before', baseline['sync_tls'], baseline['session']),
                                                   ('after', sync_tls, MoodleSession)):
                path = folder / 'case.db'
                shutil.copyfile(seed, path)
                # No worker is active; reset only this fixture's cooldown metadata.
                with sync_policy.SyncLock(path) as guard:
                    guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
                runs = []
                with patch.object(sync_policy, 'now', return_value=start + timedelta(seconds=age)):
                    for _ in range(repeats):
                        selected = list(arguments)
                        if label == 'before' and name in ('notice_fresh_equivalent', 'daily_all_scopes_due'):
                            selected = ['--full', '--metadata-only']
                        if label == 'after' and name == 'three_calls_during_retry_after':
                            selected += ['--force']
                        runs.append(run_sync(module, pages, path, *selected, recheck=False,
                                             session_class=session_class, allow_failure=True))
                        if label == 'before' and name == 'status_fresh_equivalent':
                            runs.append(run_sync(module, pages, path, '--academic-only', recheck=False,
                                                 session_class=session_class))
                row[label] = {'totals': totals(runs), 'runs': runs}
                assert all(run['failed'] == (name == 'three_calls_during_retry_after') for run in runs), name
                data[label] = snapshot(path)
                for resource in data[label]['resources']:
                    resource.pop('downloadedAt', None)
            row['same_result'] = data['before'] == data['after']
            if name == 'status_only_default':
                assert not row['same_result']
                row['reason'] = 'Before leaves submitted status stale; after refreshes it at the 15-minute boundary.'
                assert next(x for x in data['after']['assignments'] if x['id'] == 'tls-assignment-101')['submissionStatus'] == 'SUBMITTED'
            else:
                assert row['same_result'], name
            row['request_reduction_percent'] = round((1 - row['after']['totals']['requests'] /
                                                       row['before']['totals']['requests']) * 100, 2)
            report['results'].append(row)
        report['rate_limit'] = rate_comparison(baseline['session'])
    report['notes'] = [
        'All cases start from the same successfully checked data. Warm-up is excluded.',
        'Fixture login is mocked; login_calls records whether authentication was entered.',
        'No TLS requests or real credentials are used. Offline runtime is not a live speed estimate.',
        'Fresh-equivalent cases add the old explicit status/full refresh needed to get the same updated data.',
        'Status-only default comparison intentionally reports increased requests and corrected stale output.',
        'Actual two-process coalescing and crash recovery are covered by test_sync_policy.py.',
    ]
    target = REPO / 'tls-optimization-results/stage345_offline.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
