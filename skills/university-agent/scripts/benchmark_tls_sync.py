#!/usr/bin/env python3
"""Compare archived/current sync against identical offline HTTP fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT), str(ROOT / 'scripts')]
from test_tls_optimization import fixture_pages, run_sync, snapshot, load_baseline
import sync_tls
from providers.moodle_provider import MoodleTLSProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        with zipfile.ZipFile(args.baseline_archive) as archive:
            # Only the two expected source files are extracted.
            for name in ('moodle_provider.py', 'sync_tls.py'):
                (folder / name).write_bytes(archive.read(name))
        baseline = load_baseline(folder)
        before = baseline['sync_tls']
        from benchmark_tls_policy import load_stage012
        after_folder = folder / 'stage012'
        after_folder.mkdir()
        after = load_stage012(after_folder)['sync_tls']
        seed = folder / 'seed.db'
        original = fixture_pages()
        run_sync(before, original, seed, '--full', '--metadata-only')
        cases = [
            ('unchanged', 0, '--ensure', '--metadata-only'),
            ('one_course_changed', 1, '--ensure', '--metadata-only'),
            ('three_courses_changed', 3, '--ensure', '--metadata-only'),
            ('all_courses_changed', 8, '--ensure', '--metadata-only'),
            ('status_only_smart_sync', 0, '--ensure', '--metadata-only'),
            ('status_only_academic_refresh', 0, '--academic-only'),
            ('requested_missing_file', 0, '--ensure', '--resource-id', 'tls-resource-108'),
            ('course_added', 0, '--ensure', '--metadata-only'),
            ('course_removed', 0, '--ensure', '--metadata-only'),
        ]
        for name, changed_count, *arguments in cases:
            pages = dict(original)
            for i in range(1, changed_count + 1):
                pages[f'/course/view.php?id={i}'] = pages[f'/course/view.php?id={i}'].replace('과제 A', '변경된 과제 A')
            if name.startswith('status_only'):
                pages['/mod/assign/view.php?id=101'] = '<p>제출 완료</p>'
                pages['/mod/vod/viewer.php?id=103'] = '<script>var is_progress=100; var is_complete=1;</script>'
            if name == 'course_added':
                pages = fixture_pages(9)
            if name == 'course_removed':
                pages['/local/ubion/user/'] = pages['/local/ubion/user/'].replace(
                    '<a href="/course/view.php?id=8">테스트 과목 8</a>', '')
            row = {'scenario': name}
            data = {}
            for label, module in (('before', before), ('after_stage1', before), ('after', after)):
                path = folder / 'case.db'
                shutil.copyfile(seed, path)
                if label == 'after_stage1':
                    with patch.object(baseline['moodle_provider'].MoodleTLSProvider, 'preflight', MoodleTLSProvider.preflight):
                        row[label] = run_sync(module, pages, path, *arguments)
                else:
                    row[label] = run_sync(module, pages, path, *arguments)
                data[label] = snapshot(path)
                # Run-specific download timestamps are not semantic differences.
                for resource in data[label]['resources']:
                    resource.pop('downloadedAt', None)
            assert data['before'] == data['after_stage1'] == data['after'], name + ': result mismatch'
            row['same_result'] = True
            row['requests_reduction_percent'] = round(
                (1 - row['after']['requests'] / row['before']['requests']) * 100, 2)
            row['body_bytes_reduction_percent'] = round(
                (1 - row['after']['response_body_bytes'] / row['before']['response_body_bytes']) * 100, 2)
            results.append(row)
        hashes = {name: hashlib.sha256((folder / (name + '.py')).read_bytes()).hexdigest()
                  for name in ('moodle_provider', 'sync_tls')}
    report = {
        'measurement': 'offline HTTP replay, not live TLS traffic',
        'fixture': {'courses': 8, 'assignments_per_course': 2, 'lectures_per_course': 2,
                    'boards_per_course': 1, 'articles_per_course': 2, 'resources_per_course': 2},
        'notes': ['Shared urllib instrumentation includes redirects, HTTP errors and raw consumed body bytes.',
                  'Fixture timing has no network latency or rate limiter; do not use it as a live speed estimate.',
                  'Login/session verification is excluded; no real accounts are accessed.',
                  'Smart sync intentionally does not detect status-only changes; academic refresh does.',
                  'Every scenario asserts equal stored results for all three implementations.'],
        'baseline_sha256': hashes, 'results': results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
