"""Paired Python/Rust timing, including the real Python-to-Rust boundary."""
import argparse
from contextlib import nullcontext
import ctypes
import gc
import json
import math
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from python_adapter import ROOT, RustParser, PythonActivityParser, parser_class
sys.path[:0] = [str(ROOT / 'skills/university-agent/tests'), str(ROOT / 'skills/university-agent/scripts')]
from test_tls_optimization import fixture_pages, run_sync, snapshot, sync_tls
from features import sync_policy
from providers import moodle_provider

OUT = Path(__file__).parent / 'results'


def html_fixture(count):
    return '<ul><li class="section" id="section-1" aria-label="1주차">수업 일정 안내입니다.<ul>' + ''.join(
        f'<li class="activity modtype_resource"><a href="/mod/resource/view.php?id={i}&amp;x=2">자료 {i} &amp; 예제</a>'
        '<span>필요한 자료를 확인해 주세요.</span></li>' for i in range(count)) + '</ul></li></ul>'


def python_parse(html):
    parser = PythonActivityParser()
    parser.feed(html)
    return parser.items


def interval(python, rust):
    rng = random.Random(20261106)
    values = []
    for _ in range(2500):
        selected = [rng.randrange(len(python)) for _ in python]
        values.append(1 - statistics.median(rust[i] for i in selected) / statistics.median(python[i] for i in selected))
    values.sort()
    return [round(values[int(len(values) * quantile)] * 100, 3) for quantile in (.025, .975)]


def measure(name, prepare, native, samples=30, loops=1):
    rows = {key: {'wall_samples': [], 'cpu_samples': []} for key in ('python', 'rust')}
    fallback_start = native.fallbacks
    # Paired order alternates; setup, fixture copies and correctness reads are outside timers.
    for index in range(samples):
        for backend in (('python', 'rust') if index % 2 == 0 else ('rust', 'python')):
            run, cleanup = prepare(backend)
            previous_gc = gc.isenabled()
            gc.disable()
            try:
                cpu, wall = time.process_time(), time.perf_counter()
                for _ in range(loops):
                    result = run()
                elapsed = time.perf_counter() - wall
                cpu_elapsed = time.process_time() - cpu
            finally:
                if previous_gc:
                    gc.enable()
                cleanup()
            rows[backend]['wall_samples'].append(elapsed / loops)
            rows[backend]['cpu_samples'].append(cpu_elapsed / loops)
            if isinstance(result, dict) and 'requests' in result:
                rows[backend]['http_requests'] = result['requests']
                rows[backend]['response_body_bytes'] = result['response_body_bytes']
    for row in rows.values():
        row['median_seconds'] = statistics.median(row['wall_samples'])
        row['p95_seconds'] = sorted(row['wall_samples'])[math.ceil(samples * .95) - 1]
        row['median_cpu_seconds'] = statistics.median(row['cpu_samples'])
    confidence = interval(rows['python']['wall_samples'], rows['rust']['wall_samples'])
    improvement = (1 - rows['rust']['median_seconds'] / rows['python']['median_seconds']) * 100
    return {'scenario': name, 'pairs': samples, 'iterations_per_sample': loops, **rows,
            'improvement_percent': round(improvement, 3), 'paired_bootstrap_95_percent': confidence,
            'rust_fallbacks_during_measurement': native.fallbacks - fallback_start,
            'passes_20_percent_gate': improvement >= 20 and confidence[0] > 0}


def rss_bytes():
    if sys.platform == 'win32':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_uint32), ('faults', ctypes.c_uint32)] + [
                (name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak', 'paged', 'nonpaged_peak',
                                                   'nonpaged', 'pagefile', 'pagefile_peak')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.peak
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == 'darwin' else peak * 1024


def worker(backend):
    started = time.perf_counter()
    run = RustParser().parse if backend == 'rust' else python_parse
    initialization = time.perf_counter() - started
    html = html_fixture(1000)
    for _ in range(30):
        result = run(html)
    print(json.dumps({'backend': backend, 'initialization_seconds': initialization,
                      'peak_rss_bytes': rss_bytes(), 'activities': len(result)}))


def main(live=False):
    OUT.mkdir(exist_ok=True)
    native = RustParser()
    rust_class = parser_class(native)
    report = {'measurement': 'release Rust vs production Python, 30 paired samples',
              'production_backend_changed': False, 'micro': [], 'representative': []}
    for count, loops in ((10, 50), (100, 10), (1000, 1)):
        html = html_fixture(count)
        assert python_parse(html) == native.parse(html)
        def prepare(backend):
            return (lambda: python_parse(html)) if backend == 'python' else (lambda: native.parse(html)), lambda: None
        row = measure('activities_' + str(count), prepare, native, loops=loops)
        row['input_utf8_bytes'] = len(html.encode())
        row['outputs_equal'] = True
        report['micro'].append(row)
    html = html_fixture(100)
    expected = moodle_provider.MoodleTLSProvider._activity_fingerprint(html)
    with patch.object(moodle_provider, '_ActivityParser', rust_class):
        assert moodle_provider.MoodleTLSProvider._activity_fingerprint(html) == expected
    def fingerprint_prepare(backend):
        selected = patch.object(moodle_provider, '_ActivityParser', rust_class) if backend == 'rust' else nullcontext()
        selected.__enter__()
        return lambda: moodle_provider.MoodleTLSProvider._activity_fingerprint(html), lambda: selected.__exit__(None, None, None)
    report['micro'].append(measure('complete_fingerprint_100_activities', fingerprint_prepare, native, loops=3))

    with tempfile.TemporaryDirectory(prefix='rust-sync-replay-') as directory:
        folder = Path(directory)
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
                selected = patch.object(moodle_provider, '_ActivityParser', rust_class) if backend == 'rust' else nullcontext()
                selected.__enter__()
                def cleanup():
                    selected.__exit__(None, None, None)
                    assert snapshot(target) == expected
                return lambda: run_sync(sync_tls, pages, target, *arguments), cleanup
            row = measure(name, prepare, native)
            assert row['python']['http_requests'] == row['rust']['http_requests']
            row['learning_records_equal_every_sample'] = True
            report['representative'].append(row)
    report['fresh_process'] = []
    for index in range(3):
        for backend in (('python', 'rust') if index % 2 == 0 else ('rust', 'python')):
            started = time.perf_counter()
            output = subprocess.check_output([sys.executable, __file__, '--worker', backend], text=True, encoding='utf-8')
            row = json.loads(output)
            row['test_process_wall_seconds'] = time.perf_counter() - started
            report['fresh_process'].append(row)
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
        captured = list(provider._course_pages.values())
        expected = [python_parse(page) for page in captured]
        before = native.fallbacks
        assert [native.parse(page) for page in captured] == expected
        report['live_capture'] = {'courses': len(captured), 'utf8_bytes': sum(len(page.encode()) for page in captured),
                                  'activities': sum(map(len, expected)), 'outputs_equal': True,
                                  'fallback_pages': native.fallbacks - before, 'setup_http': metrics.snapshot(),
                                  'note': 'Live HTML held only in memory; no response bodies, URLs, IDs, cookies or credentials saved.'}
        def prepare(backend):
            run = python_parse if backend == 'python' else native.parse
            return lambda: [run(page) for page in captured], lambda: None
        report['live_capture']['parsing'] = measure('all_captured_course_activity_parsing', prepare, native)
    report['expansion_gate_passed'] = all(row['passes_20_percent_gate'] for row in report['representative'])
    report['notes'] = ['Rust includes UTF-8, FFI, JSON decoding and Python fallback; build time excluded.',
                       'Replay has no actual TLS latency; existing request limits are not relaxed.',
                       'Micro speedups do not pass the whole-flow gate. Production code remains Python.',
                       'Peak RSS and DLL initialization are separate diagnostics; child total includes 30 parses and is not application startup time.']
    (OUT / 'benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in report['micro'] + report['representative']:
        print(row['scenario'], round(row['python']['median_seconds'] * 1000, 3),
              round(row['rust']['median_seconds'] * 1000, 3), row['improvement_percent'], row['passes_20_percent_gate'])
    print('Expansion gate:', report['expansion_gate_passed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--worker', choices=('python', 'rust'))
    args = parser.parse_args()
    worker(args.worker) if args.worker else main(args.live)
