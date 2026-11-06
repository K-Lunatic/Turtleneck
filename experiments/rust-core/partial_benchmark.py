"""Module adoption: HTML kernels, concept ranking and real loopback exam routes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import cProfile
from datetime import datetime, timezone
import json
from pathlib import Path
import pstats
import shutil
import sqlite3
import sys
import tempfile
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from benchmark import ROOT, OUT, measure, html_fixture, python_parse
from backend import activate
from python_adapter import RustParser, PythonOverviewParser, PythonRankBucket
from test_concept import concept_bucket
from test_tls_optimization import fixture_pages, run_sync, snapshot, sync_tls
from features import sync_policy, concept_insights
from providers import moodle_provider


def python_overviews(html):
    parser = PythonOverviewParser()
    parser.feed(html)
    return parser.overviews


def overview_fixture(count):
    return '<ul>' + ''.join(f'<li class="section" id="s{i}" aria-label="주차 {i}">주차 {i}: 충분히 긴 수업 개요와 일정 설명입니다.'
        '<span hidden>숨긴 설명입니다.</span><ul><li class="activity"><a href="/x">활동 내용 제외</a></li></ul></li>'
        for i in range(count)) + '</ul>'


def create_concept_history(root, count):
    source = dict(resourceId='r1', courseId='c1', name='자료', location='p.1', quote='근거')
    db = sqlite3.connect(root / 'analysis-records.db')
    try:
        db.execute('CREATE TABLE analyses (user TEXT, id TEXT, created TEXT, value TEXT)')
        for start in range(0, count, 20):
            concepts = [dict(concept=f'개념 {i}', explanation=f'근거 있는 설명 {i}', evidence=[source],
                            importanceBySource=[dict(sourceKind='course_material', score=i % 101,
                                                     reason='본문 근거', referenceIds=['ref1'])])
                        for i in range(start, min(count, start + 20))]
            record = dict(sources=[source], data=dict(concepts=concepts))
            db.execute('INSERT INTO analyses VALUES (?,?,?,?)', ('fixture', str(start), str(start), json.dumps(record, ensure_ascii=False)))
        db.commit()
    finally:
        db.close()
    return [dict(id='r1', courseId='c1')]


def profile_call(run):
    profile = cProfile.Profile()
    profile.runcall(run)
    stats = pstats.Stats(profile)
    rows = []
    for (filename, line, name), (primitive, calls, own, cumulative, _) in stats.stats.items():
        rows.append(dict(function=Path(filename).name + ':' + name, calls=calls,
                         own_seconds=round(own, 6), cumulative_seconds=round(cumulative, 6)))
    return sorted(rows, key=lambda row: -row['cumulative_seconds'])[:12]


def web_benchmark(native, pairs=30):
    import test_exam_web
    from features.exam_web import create_exam_server
    case = test_exam_web.ExamWebTests()
    case.setUp()
    server = None
    report = []
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    clock = patch('features.study.datetime', FixedClock)
    clock.start()
    try:
        session = case.make_exam(start=True)
        server, url = create_exam_server(session)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base, token = url.split('#')
        endpoint = base.rstrip('/') + '/api/exam'
        def fetch():
            request = Request(endpoint, headers={'X-Exam-Token': token})
            with urlopen(request, timeout=10) as response:
                return response.read()
        expected = fetch()
        public = json.loads(expected)
        assert len(public['questions']) == 6
        report_profile = profile_call(lambda: session.call({'action': 'web_status'}))
        for concurrency in (1, 4):
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                def prepare(backend):
                    context = activate(native) if backend == 'rust' else nullcontext()
                    context.__enter__()
                    latest = []
                    def run():
                        latest[:] = list(pool.map(lambda _: fetch(), range(concurrency)))
                        return dict(requests=concurrency, response_body_bytes=sum(map(len, latest)))
                    def cleanup():
                        context.__exit__(None, None, None)
                        assert all(value == expected for value in latest)
                    return run, cleanup
                before = dict(native.calls_by_kind)
                row = measure(f'exam_status_http_{concurrency}_clients', prepare, native, samples=pairs, loops=3)
                row['native_calls_by_kind'] = {key: native.calls_by_kind[key] - before[key] for key in before}
                row['responses_equal'] = True
                row['questions'] = 6
                report.append(row)
        for headers in ({'Origin': 'https://other.invalid', 'X-Exam-Token': token}, {'X-Exam-Token': 'wrong'}):
            try:
                with urlopen(Request(endpoint, headers=headers), timeout=10):
                    raise AssertionError('unauthorized request was accepted')
            except HTTPError as error:
                assert error.code == 403
        return dict(routes=report, session_profile=report_profile, origin_and_token_checks_passed=True,
                    note='Existing ThreadingHTTPServer and real StudySession/SQLite with six active questions and a fixed exam clock; no Rust HTTP server rewrite. No answers or exam state are published.')
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        clock.stop()
        case.doCleanups()


def main(live=False):
    native = RustParser()
    report = dict(activity=[], overview=[], concept_rank=[], concept_flow=[], representative=[],
                  policy='Module >=20% median gain, positive paired interval, equal outputs; accepted path must stay within 5% whole-flow regression.')
    for module, counts in (('activity', (100, 1000)), ('overview', (100, 1000))):
        for count in counts:
            html = html_fixture(count) if module == 'activity' else overview_fixture(count)
            python = python_parse if module == 'activity' else python_overviews
            rust = native.parse if module == 'activity' else native.overviews
            assert python(html) == rust(html)
            def prepare(backend):
                return (lambda: python(html)) if backend == 'python' else (lambda: rust(html)), lambda: None
            row = measure(module + '_' + str(count), prepare, native, loops=3 if count == 100 else 1)
            row['outputs_equal'] = True
            report[module].append(row)
    for count in (100, 1000):
        bucket = concept_bucket(count)
        assert native.rank_concepts(bucket, 20) == PythonRankBucket(bucket, 20)
        def prepare(backend):
            return (lambda: PythonRankBucket(bucket, 20)) if backend == 'python' else (lambda: native.rank_concepts(bucket, 20)), lambda: None
        before = native.concept_fallbacks
        row = measure('concept_rank_' + str(count), prepare, native)
        row.update(outputs_equal=True, concept_fallbacks=native.concept_fallbacks - before)
        report['concept_rank'].append(row)
    with tempfile.TemporaryDirectory(prefix='partial-native-') as directory:
        folder = Path(directory)
        for count in (100, 1000):
            root = folder / str(count)
            root.mkdir()
            resources = create_concept_history(root, count)
            expected = concept_insights.build_insights(root, 'fixture', resources)
            with patch.object(concept_insights, '_rank_bucket', native.rank_concepts):
                assert concept_insights.build_insights(root, 'fixture', resources) == expected
            def prepare(backend):
                context = patch.object(concept_insights, '_rank_bucket', native.rank_concepts) if backend == 'rust' else nullcontext()
                context.__enter__()
                latest = []
                def run():
                    result = concept_insights.build_insights(root, 'fixture', resources)
                    latest[:] = [result]
                    return result
                def cleanup():
                    context.__exit__(None, None, None)
                    assert latest[0] == expected
                return run, cleanup
            row = measure('concept_insights_from_sqlite_' + str(count), prepare, native)
            row['outputs_equal'] = True
            row['python_profile'] = profile_call(lambda: concept_insights.build_insights(root, 'fixture', resources))
            report['concept_flow'].append(row)
        pages = fixture_pages(8)
        seed = folder / 'seed.db'
        run_sync(sync_tls, pages, seed, '--full', '--metadata-only')
        expected = snapshot(seed)
        for name, arguments in (('unchanged_catalog_sync', ['--ensure', '--metadata-only']),
                                 ('full_metadata_sync', ['--full', '--metadata-only'])):
            def prepare(backend):
                target = folder / 'case.db'
                shutil.copyfile(seed, target)
                with sync_policy.SyncLock(target) as guard:
                    guard.record(sync_policy.scope_key('https://tls.kku.ac.kr', 'fixture'))
                context = activate(native) if backend == 'rust' else nullcontext()
                context.__enter__()
                def cleanup():
                    context.__exit__(None, None, None)
                    assert snapshot(target) == expected
                return lambda: run_sync(sync_tls, pages, target, *arguments), cleanup
            before = dict(native.calls_by_kind)
            row = measure(name, prepare, native)
            row.update(outputs_equal=True, native_calls_by_kind={key: native.calls_by_kind[key] - before[key] for key in before})
            assert row['python']['http_requests'] == row['rust']['http_requests']
            report['representative'].append(row)
    (OUT / 'partial-benchmark.checkpoint.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report['web'] = web_benchmark(native)
    if live:
        from providers.credentials import load
        from providers.moodle_session import MoodleSession
        from providers.request_metrics import RequestMetrics
        username, password = load()
        metrics = RequestMetrics()
        session = MoodleSession(metrics=metrics)
        session.login(username, password)
        del password
        provider = moodle_provider.MoodleTLSProvider(session)
        provider.preflight(username)
        pages = list(provider._course_pages.values())
        before = native.fallbacks
        expected = [python_overviews(page) for page in pages]
        assert [native.overviews(page) for page in pages] == expected
        report['live'] = dict(courses=len(pages), overview_records=sum(map(len, expected)),
                             outputs_equal=True, fallback_pages=native.fallbacks - before, setup_http=metrics.snapshot())
        def prepare(backend):
            context = activate(native) if backend == 'rust' else nullcontext()
            context.__enter__()
            return lambda: [moodle_provider.MoodleTLSProvider._activity_fingerprint(page) for page in pages], lambda: context.__exit__(None, None, None)
        reference = [moodle_provider.MoodleTLSProvider._activity_fingerprint(page) for page in pages]
        with activate(native):
            assert [moodle_provider.MoodleTLSProvider._activity_fingerprint(page) for page in pages] == reference
        report['live']['complete_fingerprints'] = measure('captured_course_complete_fingerprints', prepare, native)
    report['notes'] = ['New phase: old activity-pilot evidence is retained unchanged.',
                       'FFI, encoding and JSON conversion are included. Permission filtering/DB reads remain Python.',
                       'Concept ranking is a local scoring prototype, not replacement of host AI semantic analysis.',
                       'Web measurements use loopback HTTP and existing route/session logic, not a ported Rust web server.',
                       'TLS replay has no actual network latency. Real HTML is kept only in memory.']
    (OUT / 'partial-benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for group in ('activity', 'overview', 'concept_rank', 'concept_flow', 'representative'):
        for row in report[group]:
            print(row['scenario'], round(row['python']['median_seconds'] * 1000, 3),
                  round(row['rust']['median_seconds'] * 1000, 3), row['improvement_percent'])
    for row in report['web']['routes']:
        print(row['scenario'], round(row['python']['median_seconds'] * 1000, 3),
              round(row['rust']['median_seconds'] * 1000, 3), row['native_calls_by_kind'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    main(parser.parse_args().live)
