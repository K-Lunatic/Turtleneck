"""Live notice reads and isolated copies of the user's DB; persist aggregates only."""
from copy import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = REPO / 'tls-optimization-stage78-results'
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from benchmark_tls_notices_storage import load_stage06, database_snapshot
from providers.credentials import load
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import MoodleSession
from providers.request_metrics import RequestMetrics
from storage.local_db import LocalDatabase


def main():
    username, password = load()
    auth_metrics = RequestMetrics()
    auth = MoodleSession(metrics=auth_metrics)
    auth.login(username, password)
    del password
    source = Path(os.environ.get('UNIVERSITY_AGENT_DB', Path.home() / '.university-agent/university.db'))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    def session(metrics):
        result = MoodleSession(metrics=metrics)
        for cookie in auth.cookies:
            result.cookies.set_cookie(copy(cookie))
        result.logged_in = True
        return result
    setup_metrics = RequestMetrics()
    setup = MoodleTLSProvider(session(setup_metrics))
    preflight = setup.preflight(username)
    candidates = [course for course in setup.get_courses(username)
                  if '/mod/ubboard/view.php' in setup._course_page(course)]
    if not candidates:
        raise RuntimeError('No notice board is available for comparison.')
    course = candidates[0]
    prepared = setup.for_courses(username, {course['id']}).get_notices(username, notice_cache={})
    cache = {row['id']: row.pop('_notice_check') for row in prepared if '_notice_check' in row}
    report = {'measurement': 'live warm notice reread and isolated local DB snapshot rewrite',
              'courses_in_preflight': len(preflight['courseIds']),
              'authentication_setup': auth_metrics.snapshot(), 'preparation': setup_metrics.snapshot(),
              'prepared_notice_records': len(prepared),
              'cacheable_articles': sum(bool(value.get('fingerprint')) for value in cache.values())}
    with tempfile.TemporaryDirectory(prefix='tls-notice-storage-measure-') as directory:
        folder = Path(directory)
        old = load_stage06(folder)
        returned = {}
        for label, provider_class in (('before', old['moodle_provider'].MoodleTLSProvider), ('after', MoodleTLSProvider)):
            metrics = RequestMetrics()
            provider = provider_class(session(metrics))
            provider._courses = [course]
            provider._course_pages = setup._course_pages.copy()
            kwargs = {} if label == 'before' else {'existing_notices': prepared, 'notice_cache': cache}
            rows = provider.get_notices(username, **kwargs)
            report[label] = metrics.snapshot()
            if label == 'after':
                report['reused_notice_bodies'] = sum(bool(row.get('_notice_reused')) for row in rows)
            returned[label] = [{key: value for key, value in row.items() if not key.startswith('_')} for row in rows]
        report['notice_results_equal'] = returned['before'] == returned['after']
        user = os.environ.get('UNIVERSITY_AGENT_USER_ID', username)
        seed = folder / 'seed.db'
        original = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
        target = sqlite3.connect(seed)
        try:
            original.backup(target)
        finally:
            original.close()
            target.close()
        db = LocalDatabase(seed)
        try:
            profile = db.get_user(user)
            payload = {kind: getattr(db, 'get_' + kind)(user) for kind in ('courses', 'assignments', 'lectures', 'notices', 'activities')}
            payload['assignments'] = [row for row in payload['assignments'] if row.get('source') != 'manual']
            payload['resources'] = db.get_resources(user, include_permissions=False)
        finally:
            db.close()
        if not profile or not payload['courses']:
            raise RuntimeError('No source academic snapshot is available for local DB comparison.')
        report['database'] = {'record_counts': {kind: len(rows) for kind, rows in payload.items()}}
        data = {}
        for label, db_class in (('before', old['local_db'].LocalDatabase), ('after', LocalDatabase)):
            path = folder / 'case.db'
            shutil.copyfile(seed, path)
            db = db_class(path)
            changed = db.connection.total_changes
            started = time.perf_counter()
            db.upsert_tls_snapshot(user, payload['courses'], payload['assignments'], payload['lectures'],
                                   profile['name'], profile.get('department'), notices=payload['notices'],
                                   resources=payload['resources'], activities=payload['activities'])
            report['database'][label] = {'changed_rows': db.connection.total_changes - changed,
                                         'elapsed_seconds': round(time.perf_counter() - started, 6)}
            data[label] = database_snapshot(db)
            db.close()
        report['database']['learning_records_equal'] = data['before'] == data['after']
    report['source_db_bytes_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report['notes'] = ['Notice comparison is a warm provider reread, excluding authentication/preflight/preparation.',
                       'It is not a forced refresh, a file-permission check or a six-hour expired refresh.',
                       'Same cached course page, same account; sequential single samples. No original file downloads.',
                       'Local DB writes are measured only on temporary SQLite backup copies.',
                       'Modified-row counts are not physical disk bytes, page writes or school-server DB load.',
                       'Only aggregate counters and equality flags are retained; source user DB is untouched.']
    (OUT / 'live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert report['notice_results_equal'] and report['database']['learning_records_equal'] and report['source_db_bytes_unchanged']
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
