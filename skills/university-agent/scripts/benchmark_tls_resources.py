"""Stage 6 comparison against archived stage 0-5 using identical offline HTTP."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT = REPO / 'tls-optimization-stage6-results'
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
from test_tls_optimization import fixture_pages, run_sync, snapshot, load_baseline
from features import sync_policy
import sync_tls


def load_stage05(directory):
    with zipfile.ZipFile(OUT / 'stage05_sources.zip') as archive:
        for name in ('providers/moodle_provider.py', 'scripts/sync_tls.py'):
            (Path(directory) / Path(name).name).write_bytes(archive.read(name))
    return load_baseline(directory)['sync_tls']


def resource_fixture(count):
    pages = fixture_pages(8)
    identifiers = [108, 109]
    for number in range(count - 2):
        identifier = 10000 + number
        identifiers.append(identifier)
        link = f'<li class="activity"><a href="/mod/ubfile/view.php?id={identifier}">추가 자료 {number}.pdf</a></li>'
        pages['/course/view.php?id=1'] += link
        pages[f'/mod/ubfile/view.php?id={identifier}'] = (
            f'<iframe src="/local/ubdoc/?id={identifier}&amp;tp=m&amp;pg=ubfile"></iframe>')
        pages[f'/local/ubdoc/download.php?id={identifier}&tp=m&pg=ubfile'] = b'%PDF-fixture-original'
    return pages, ['tls-resource-' + str(value) for value in identifiers]


def main():
    instant = datetime(2026, 11, 6, tzinfo=timezone.utc)
    report = {'measurement': 'offline HTTP replay; not live TLS traffic',
              'baseline': 'stages 0-5', 'after': 'stages 0-6', 'courses': 8, 'results': []}
    cases = [(2, 1, 'fresh'), (20, 1, 'fresh'), (20, 3, 'fresh'), (20, 20, 'fresh'),
             (100, 1, 'fresh'), (20, 1, 'force'), (20, 1, 'expired'), (20, 1, 'changed')]
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        before = load_stage05(folder)
        for count, selected_count, condition in cases:
            pages, identifiers = resource_fixture(count)
            seed = folder / 'seed.db'
            if seed.exists():
                seed.unlink()
            with sync_policy.SyncLock(seed) as guard:
                guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
            with patch.object(sync_policy, 'now', return_value=instant):
                run_sync(before, pages, seed, '--full', '--metadata-only', recheck=False)
            if condition == 'changed':
                pages['/course/view.php?id=1'] = pages['/course/view.php?id=1'].replace('과제 A', '변경 과제 A')
            row = {'resources_in_target_course': count, 'selected': selected_count, 'condition': condition}
            data, binaries = {}, {}
            arguments = ['--ensure']
            for identifier in identifiers[:selected_count]:
                arguments.extend(['--resource-id', identifier])
            if condition == 'force':
                arguments.append('--force')
            age = timedelta(days=1) if condition == 'expired' else timedelta(minutes=1)
            for label, module in (('before', before), ('after', sync_tls)):
                path = folder / 'case.db'
                shutil.copyfile(seed, path)
                with sync_policy.SyncLock(path) as guard:
                    guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
                with patch.object(sync_policy, 'now', return_value=instant + age):
                    row[label] = run_sync(module, pages, path, *arguments, recheck=False)
                data[label] = snapshot(path)
                binaries[label] = {}
                for resource in data[label]['resources']:
                    resource.pop('downloadedAt', None)
                    if resource.get('localPath'):
                        binaries[label][resource['id']] = hashlib.sha256(Path(resource['localPath']).read_bytes()).hexdigest()
            assert data['before'] == data['after'], (count, selected_count, condition)
            assert binaries['before'] == binaries['after'] and len(binaries['after']) == selected_count
            row['stored_results_equal'] = True
            row['downloaded_files_equal'] = True
            row['request_reduction_percent'] = round((1 - row['after']['requests'] / row['before']['requests']) * 100, 2)
            row['body_reduction_percent'] = round((1 - row['after']['response_body_bytes'] / row['before']['response_body_bytes']) * 100, 2)
            report['results'].append(row)
    report['notes'] = ['All cases use the same initial DB and HTTP responses; preparation excluded.',
                       'Actual login is mocked. Request spacing is disabled: runtime is not a live speed estimate.',
                       'Notice restrictions are rechecked. Forced/expired/changed scopes retain full detail reads.',
                       'Unselected records and selected file SHA-256 values are compared.',
                       'No real TLS requests, credentials, user DB writes or file downloads are used.']
    (OUT / 'offline.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in report['results']:
        print(row['resources_in_target_course'], row['selected'], row['condition'],
              row['before']['requests'], row['after']['requests'],
              row['before']['response_body_bytes'], row['after']['response_body_bytes'])


if __name__ == '__main__':
    main()
