"""Stages 7/8: fixed HTTP replay and actual local SQLite change counters."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = REPO / 'tls-optimization-stage78-results'
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from test_tls_optimization import run_sync, snapshot
from test_notice_storage_optimization import notice_fixture, storage_payload, write_payload
from features import sync_policy
from storage.local_db import LocalDatabase
import sync_tls


def load_stage06(folder):
    modules = {}
    with zipfile.ZipFile(OUT / 'stage06_sources.zip') as archive:
        for name in ('providers/moodle_provider.py', 'scripts/sync_tls.py', 'storage/local_db.py'):
            path = Path(folder) / Path(name).name
            path.write_bytes(archive.read(name))
            spec = importlib.util.spec_from_file_location('stage06_' + path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules[path.stem] = module
    modules['local_db'].SCHEMA = ROOT / 'database/schema.sql'
    modules['sync_tls'].MoodleTLSProvider = modules['moodle_provider'].MoodleTLSProvider
    modules['sync_tls'].LocalDatabase = modules['local_db'].LocalDatabase
    return modules


def database_snapshot(db):
    result = {}
    for table in ('users', 'courses', 'enrollments', 'assignments', 'assignment_submissions',
                  'lectures', 'lecture_progress', 'notices', 'resources', 'course_activities'):
        result[table] = [{key: value for key, value in dict(row).items() if key not in ('updated_at', 'created_at')}
                         for row in db.connection.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
    return result


@contextmanager
def database_counters():
    counts = {'changed_rows': 0, 'sql_statements': 0, 'write_statements_attempted': 0}
    connect = sqlite3.connect
    class Connection(sqlite3.Connection):
        counted = False
        def close(self):
            if not self.counted:
                counts['changed_rows'] += self.total_changes
                self.counted = True
            return super().close()
    def trace(sql):
        counts['sql_statements'] += 1
        if sql.lstrip().split(None, 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'):
            counts['write_statements_attempted'] += 1
    def measured(*args, **kwargs):
        connection = connect(*args, **kwargs, factory=Connection)
        connection.set_trace_callback(trace)
        return connection
    with patch('sqlite3.connect', side_effect=measured):
        yield counts


def main():
    instant = datetime(2026, 11, 6, tzinfo=timezone.utc)
    report = {'baseline': 'stage 0-6', 'after': 'stage 0-8', 'http_replay': [], 'sqlite': []}
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        old = load_stage06(folder)
        old_db = old['local_db'].LocalDatabase
        cases = [('course_changed_2_notices', 2), ('course_changed_20_notices', 20),
                 ('course_changed_100_notices', 100), ('new_notice', 20), ('edited_row', 20),
                 ('read_counter_only', 20), ('removed_notice', 20), ('six_hours_due', 20),
                 ('forced', 20), ('file_permission_check', 20), ('unknown_markup', 20), ('cold_cache', 20)]
        for scenario, count in cases:
            pages = notice_fixture(courses=8, articles=count)
            seed = folder / 'seed.db'
            if seed.exists():
                seed.unlink()
            with sync_policy.SyncLock(seed) as guard:
                guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
            with patch.object(sync_policy, 'now', return_value=instant):
                run_sync(sync_tls, pages, seed, '--full', '--metadata-only', recheck=False)
            arguments = ['--ensure', '--metadata-only']
            age = timedelta(minutes=5)
            if scenario != 'six_hours_due':
                pages['/course/view.php?id=1'] = pages['/course/view.php?id=1'].replace('과제 A', '변경 과제 A')
            else:
                age = timedelta(hours=6)
            if scenario == 'forced':
                arguments.append('--force')
            if scenario == 'file_permission_check':
                arguments += ['--resource-id', 'tls-resource-108']
            if scenario == 'new_notice':
                pages['/mod/ubboard/view.php?id=105'] += '<table><tr><td><a href="/mod/ubboard/article.php?id=105&bwid=30000">새 공지</a></td></tr></table>'
                pages['/mod/ubboard/article.php?id=105&bwid=30000'] = '<div class="subject"><h3>새 공지</h3></div>'
            if scenario == 'edited_row':
                pages['/mod/ubboard/view.php?id=105'] = pages['/mod/ubboard/view.php?id=105'].replace('공지 0', '수정 공지')
                pages['/mod/ubboard/article.php?id=105&bwid=106'] = '<div class="subject"><h3>수정 공지</h3></div>'
            if scenario == 'read_counter_only':
                pages['/mod/ubboard/view.php?id=105'] = pages['/mod/ubboard/view.php?id=105'].replace('class="hit">0', 'class="hit">99')
            if scenario == 'removed_notice':
                pages['/mod/ubboard/view.php?id=105'] = pages['/mod/ubboard/view.php?id=105'].replace(
                    '<tr><td class="title"><a href="/mod/ubboard/article.php?id=105&amp;bwid=106">공지 0</a></td><td class="date">2026-11-01</td><td class="hit">0</td></tr>', '')
            if scenario == 'unknown_markup':
                pages['/mod/ubboard/view.php?id=105'] = pages['/mod/ubboard/view.php?id=105'].replace('<tr>', '<div>').replace('</tr>', '</div>')
            if scenario == 'cold_cache':
                db = LocalDatabase(seed)
                try:
                    with db.connection:
                        db.connection.execute("DELETE FROM sync_state WHERE state_key='notice_detail_checks'")
                finally:
                    db.close()
            row = {'scenario': scenario, 'notices_in_target_course': count}
            data = {}
            for label, module, db_class in (('stage06', old['sync_tls'], old_db),
                                            ('stage07', sync_tls, old_db), ('stage08', sync_tls, LocalDatabase)):
                path = folder / 'case.db'
                shutil.copyfile(seed, path)
                with sync_policy.SyncLock(path) as guard:
                    guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
                with patch.object(module, 'LocalDatabase', db_class), \
                     patch.object(sync_policy, 'now', return_value=instant + age), database_counters() as counts:
                    row[label] = run_sync(module, pages, path, *arguments, recheck=False)
                row[label]['database'] = dict(counts)
                data[label] = snapshot(path)
            assert data['stage06'] == data['stage07'] == data['stage08'], scenario
            row['learning_records_equal'] = True
            report['http_replay'].append(row)

        for count in (20, 1000):
            for scenario in ('unchanged_snapshot', 'one_submission_changed', 'one_resource_restricted'):
                initial = storage_payload(count)
                data = deepcopy(initial)
                if scenario == 'one_submission_changed':
                    data['assignments'][0]['submissionStatus'] = 'SUBMITTED'
                if scenario == 'one_resource_restricted':
                    data['resources'][0].update(downloadStatus='PROHIBITED', downloadReason='금지')
                row = {'scenario': scenario, 'records_per_kind': count, 'repetitions': 5}
                final = {}
                for label, db_class in (('before', old_db), ('after', LocalDatabase)):
                    seed = folder / 'db-seed.db'
                    if seed.exists():
                        seed.unlink()
                    db = db_class(seed)
                    write_payload(db, initial)
                    db.close()
                    durations, changes, statements = [], [], []
                    for index in range(5):
                        target = folder / 'trial.db'
                        shutil.copyfile(seed, target)
                        db = db_class(target)
                        traced = []
                        db.connection.set_trace_callback(lambda sql: traced.append(sql.split(None, 1)[0]))
                        previous = db.connection.total_changes
                        started = time.perf_counter()
                        write_payload(db, data, stamp=f'2026-11-06T01:00:0{index}+00:00')
                        durations.append(time.perf_counter() - started)
                        changes.append(db.connection.total_changes - previous)
                        statements.append(len(traced))
                        final[label] = database_snapshot(db)
                        db.close()
                    assert len(set(changes)) == 1
                    row[label] = {'changed_rows': changes[0], 'sql_statements': statements[0],
                                  'median_seconds': round(statistics.median(durations), 6),
                                  'elapsed_samples': [round(value, 6) for value in durations]}
                assert final['before'] == final['after']
                row['learning_records_equal'] = True
                report['sqlite'].append(row)
        for scenario in ('unchanged_state', 'one_state_key_changed'):
            row = {'scenario': scenario, 'keys': 100}
            for label, db_class in (('before', old_db), ('after', LocalDatabase)):
                path = folder / 'state.db'
                if path.exists():
                    path.unlink()
                db = db_class(path)
                write_payload(db, storage_payload(1))
                values = {str(key): str(key) for key in range(100)}
                db.save_sync_state('fixture', values)
                previous = db.connection.total_changes
                db.merge_sync_state('fixture', {'0': 'changed' if scenario == 'one_state_key_changed' else '0'})
                row[label] = {'changed_rows': db.connection.total_changes - previous}
                expected = dict(values, **({'0': 'changed'} if scenario == 'one_state_key_changed' else {}))
                assert db.get_sync_state('fixture') == expected
                db.close()
            report['sqlite'].append(row)
    report['notes'] = ['HTTP is offline replay with mocked login; timings are not live network speed.',
                       'SQLite counters measure modified rows via total_changes, not physical page writes or server DB load.',
                       'Conditional UPSERTs still execute SQL and read/compare rows; statement counts need not decrease.',
                       'The user sync timestamp is always written. Unchanged content timestamps are retained.',
                       'Notice cache is warm except cold_cache; six-hour body refresh and permission reads stay full.']
    (OUT / 'offline.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in report['http_replay']:
        print(row['scenario'], [(label, row[label]['requests'], row[label]['database']['changed_rows'])
                                 for label in ('stage06', 'stage07', 'stage08')])
    for row in report['sqlite']:
        print(row['scenario'], row.get('records_per_kind', row.get('keys')),
              row['before']['changed_rows'], row['after']['changed_rows'])


if __name__ == '__main__':
    main()
