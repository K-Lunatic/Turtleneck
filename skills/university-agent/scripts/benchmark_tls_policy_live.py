"""Measure status refresh/reuse on private DB copies; save aggregate counters only."""
from contextlib import closing, redirect_stdout, redirect_stderr
from copy import copy
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from benchmark_tls_policy import load_stage012
from providers.credentials import load
from providers.moodle_session import MoodleSession
from providers.request_metrics import RequestMetrics
from storage.local_db import LocalDatabase
import sync_tls


def main():
    username, password = load()
    auth_metrics = RequestMetrics()
    auth = MoodleSession(metrics=auth_metrics)
    auth.login(username, password)
    del password
    source = Path(os.environ.get('UNIVERSITY_AGENT_DB', Path.home() / '.university-agent/university.db'))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {'measurement': 'live TLS academic refresh, warm reuse, forced refresh',
              'authentication_setup': auth_metrics.snapshot()}

    def run(module, session_class, path, force=False):
        metrics = RequestMetrics()
        session = session_class(metrics=metrics)
        for cookie in auth.cookies:
            session.cookies.set_cookie(copy(cookie))
        session.logged_in = True
        with patch.object(sys, 'argv', ['sync_tls.py', '--academic-only', *(['--force'] if force else [])]), \
             patch.dict(os.environ, {'UNIVERSITY_AGENT_DB': str(path), 'UNIVERSITY_AGENT_USER_ID': username}), \
             patch.object(module, '_login_with_retries', return_value=(username, session)) as login, \
             patch.object(module, 'load_username', return_value=username, create=True), \
             redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            module.main()
        with closing(LocalDatabase(path, read_only=True)) as db:
            data = {kind: sorted([{key: value for key, value in row.items()
                                  if key not in ('updatedAt', 'updated_at', 'lastSyncedAt')}
                                 for row in getattr(db, 'get_' + kind)(username)], key=lambda row: row['id'])
                    for kind in ('assignments', 'lectures')}
            stamp = db.get_sync_state(username).get('academic_checked_at')
        return {**metrics.snapshot(), 'login_entry_calls': login.call_count}, data, stamp

    with tempfile.TemporaryDirectory(prefix='tls-policy-measure-') as directory:
        folder = Path(directory)
        old = load_stage012(folder)
        seed = folder / 'seed.db'
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original, \
             closing(sqlite3.connect(seed)) as target:
            original.backup(target)
        report['preparation'], seed_data, seed_stamp = run(sync_tls, MoodleSession, seed, True)
        data, stamps = {}, {}
        for label, module, session_class, force in (
                ('before', old['sync_tls'], old['session'], False),
                ('after_reuse', sync_tls, MoodleSession, False),
                ('after_force', sync_tls, MoodleSession, True)):
            path = folder / (label + '.db')
            shutil.copyfile(seed, path)
            report[label], data[label], stamps[label] = run(module, session_class, path, force)
        report['reuse_preserves_data_and_timestamp'] = data['after_reuse'] == seed_data and stamps['after_reuse'] == seed_stamp
        report['forced_results_equal'] = data['before'] == data['after_force']
        report['record_counts'] = {kind: len(rows) for kind, rows in seed_data.items()}
    report['source_db_bytes_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    report['notes'] = ['Authentication and preparation excluded from compared runs; same authenticated cookies.',
                       'Warm reuse measured within 15 minutes of success. Forced refresh always reads current status.',
                       'Sequential single samples; server content and latency can vary. No file downloads.',
                       'Only aggregate counters and equality flags are retained; source DB is read-only.']
    target = REPO / 'tls-optimization-results/stage345_live.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert report['source_db_bytes_unchanged'] and report['reuse_preserves_data_and_timestamp']
    assert report['forced_results_equal'], 'Live statuses changed between sequential runs; inspect aggregate report.'
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
