"""Two controlled read-only TLS runs. Persist aggregate measurements only."""
from contextlib import closing, redirect_stdout, redirect_stderr
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
import sync_tls
from providers.credentials import load
from providers.moodle_provider import MoodleTLSProvider
from providers.moodle_session import MoodleSession
from providers.request_metrics import RequestMetrics
from storage.local_db import LocalDatabase
from test_tls_optimization import load_baseline


def main():
    auth_metrics = RequestMetrics()
    username, password = load()
    session = MoodleSession(metrics=auth_metrics)
    session.login(username, password)
    del password
    source = Path(os.environ.get('UNIVERSITY_AGENT_DB', Path.home() / '.university-agent' / 'university.db'))
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='turtleneck-live-measure-') as directory:
        folder = Path(directory)
        with zipfile.ZipFile(REPO / 'tls-optimization-results/baseline_sources.zip') as archive:
            for name in ('moodle_provider.py', 'sync_tls.py'):
                (folder / name).write_bytes(archive.read(name))
        before = load_baseline(folder)['sync_tls']
        seed = folder / 'seed.db'
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original, \
             closing(sqlite3.connect(seed)) as target:
            original.backup(target)
        setup_metrics = RequestMetrics()
        setup_session = session.fork()
        setup_session.metrics = setup_metrics
        setup_session._build_opener()
        provider = MoodleTLSProvider(setup_session)
        preflight = provider.preflight(username)
        if not preflight['courseIds']:
            raise RuntimeError('No courses available for measurement')
        selected = preflight['courseIds'][0]
        forced = dict(preflight['fingerprints'])
        forced[selected] = 'controlled-refresh-required'
        # Same starting state for both runs; no actual TLS course is modified.
        with closing(LocalDatabase(seed)) as database:
            database.save_sync_state(username, {
                'course_ids': json.dumps(preflight['courseIds']),
                'course_fingerprints': json.dumps(forced),
                'resource_response_version': MoodleTLSProvider.RESOURCE_RESPONSE_VERSION,
            })
        report = {
            'measurement': 'live TLS, controlled one-course fingerprint mismatch',
            'metadata_only': True, 'courses': len(preflight['courseIds']),
            'authentication_setup': auth_metrics.snapshot(), 'preflight_setup': setup_metrics.snapshot(),
            'notes': ['Both runs start from the same private DB backup and use the same authenticated account.',
                      'Only a local fingerprint is altered to force one course refresh. TLS is not modified.',
                      'Authentication and setup preflight are separate from compared sync measurements.',
                      'Only aggregate counters are saved. Response bodies, URLs, course IDs and credentials are not saved.',
                      'No raw original file bytes are downloaded; metadata/viewer/status requests may still occur.',
                      'Two live runs are sequential; changing server content and network conditions affect byte/time comparisons.'],
        }
        data = {}
        seed_data = None
        for label, module in (('before', before), ('after', sync_tls)):
            path = folder / 'case.db'
            shutil.copyfile(seed, path)
            metrics = RequestMetrics()
            child = session.fork()
            child.metrics = metrics
            child._build_opener()
            with patch.object(sys, 'argv', ['sync_tls.py', '--ensure', '--metadata-only']), \
                 patch.dict(os.environ, {'UNIVERSITY_AGENT_DB': str(path), 'UNIVERSITY_AGENT_USER_ID': username}), \
                 patch.object(module, '_login_with_retries', return_value=(username, child)), \
                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                module.main()
            report[label] = metrics.snapshot()
            # Only equality flags and counts leave this private temporary directory.
            with closing(LocalDatabase(path, read_only=True)) as database:
                data[label] = {kind: getattr(database, 'get_' + kind)(username)
                               for kind in ('assignments', 'lectures', 'notices', 'resources', 'activities')}
            if label == 'after':
                with closing(LocalDatabase(seed, read_only=True)) as database:
                    seed_data = {kind: getattr(database, 'get_' + kind)(username) for kind in data[label]}
        def normalized(rows, selected_only):
            return sorted([{key: value for key, value in row.items()
                            if key not in ('updatedAt', 'updated_at', 'downloadedAt')}
                           for row in rows if (row.get('courseId') == selected) == selected_only],
                          key=lambda row: row['id'])
        report['selected_course_results_equal'] = {
            kind: normalized(data['before'][kind], True) == normalized(data['after'][kind], True)
            for kind in data['before']}
        report['unselected_records_preserved'] = {
            kind: normalized(seed_data[kind], False) == normalized(data['after'][kind], False)
            for kind in seed_data}
        report['selected_course_record_counts'] = {
            kind: sum(row.get('courseId') == selected for row in rows) for kind, rows in data['after'].items()}
    report['source_db_bytes_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    for key in ('requests', 'response_body_bytes', 'elapsed_seconds'):
        report[key + '_reduction_percent'] = round((1 - report['after'][key] / report['before'][key]) * 100, 2)
    output = REPO / 'tls-optimization-results/live.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
