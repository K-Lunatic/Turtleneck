"""Run deterministic, offline benchmarks for each local Turtleneck part."""
from __future__ import annotations

import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo


PARTS = {
    'study_pipeline': {
        'role': '파일별 분석·문제은행·캐시 재사용의 로컬 처리',
        'files': ['experiments/study-generation/benchmark.py', 'skills/university-agent/features/study.py',
                  'skills/university-agent/features/study_pipeline.py'],
    },
    'material_cache': {
        'role': '자료 본문·분석 결과의 로컬 캐시 병렬 조회',
        'files': ['skills/university-agent/features/material_cache.py'],
    },
    'study_storage': {
        'role': '시험 분석 중간 상태와 문제은행의 로컬 SQLite 저장',
        'files': ['skills/university-agent/features/study.py', 'skills/university-agent/features/study_pipeline.py'],
    },
    'lecture_media': {
        'role': '완료 강의 미디어 조각의 검증·순서 보존 다운로드',
        'files': ['skills/university-agent/providers/lecture_media.py'],
    },
    'tls_sync': {
        'role': 'TLS 목록·과제·강의의 변경 감지와 부분 동기화',
        'files': ['skills/university-agent/scripts/sync_tls.py', 'skills/university-agent/providers/moodle_provider.py'],
    },
    'local_asr': {
        'role': '완료 강의의 로컬 음성 전사와 GPU 실패 대체 경로',
        'files': ['skills/university-agent/features/lecture_review.py'],
    },
}
KST = ZoneInfo('Asia/Seoul')


def _timestamp():
    return datetime.now(KST).isoformat(timespec='milliseconds')


def _import(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _median(rows):
    return {key: statistics.median(row[key] for row in rows)
            for key in rows[0]
            if all(isinstance(row[key], (int, float)) and not isinstance(row[key], bool) for row in rows)}


def _environment(repo: Path, commit_override=None):
    commit = commit_override or subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, check=True,
                                               capture_output=True, text=True).stdout.strip()
    try:
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=repo, check=True,
                                    capture_output=True, text=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        dirty = None
    available = getattr(os, 'sched_getaffinity', lambda _pid: set())(0)
    return {
        'commit': commit,
        'commitShort': commit[:12],
        'workingTreeDirty': dirty,
        'python': platform.python_version(),
        'pythonExecutable': sys.executable,
        'os': platform.platform(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'logicalCores': os.cpu_count(),
        'availableCores': len(available) or None,
    }


def _study(repo: Path, samples: int):
    module = _import(repo / 'experiments/study-generation/benchmark.py', 'study_benchmark')
    scenarios = {}
    for files in (1, 4):
        rows = [module.run(files) for _ in range(samples)]
        scenarios[f'{files}_files'] = {'samples': rows, 'median': _median(rows)}
    return {'status': 'measured', 'aiLatencyMeasured': False, 'scenarios': scenarios}


def _study_storage(repo: Path, samples: int):
    sys.path.insert(0, str(repo / 'skills/university-agent/tests'))
    sys.path.insert(0, str(repo / 'skills/university-agent'))
    from test_study_pipeline import FilePipelineTests
    if not hasattr(FilePipelineTests, 'test_chunk_boundaries_preserved_without_suffix_copy'):
        return {'status': 'not_available', 'reason': '이 버전의 테스트 fixture가 현재 저장 기준을 제공하지 않음.'}
    rows = []
    for _ in range(samples):
        fixture = FilePipelineTests('test_chunk_boundaries_preserved_without_suffix_copy')
        fixture.setUp()
        try:
            session = fixture.session('pipeline')
            prepared = fixture.request()
            while prepared.get('needsExtraction'):
                items = []
                for request in prepared['hostOnly']['requests']:
                    question = fixture.candidate({'hostOnly': request})
                    items.append({'requestId': request['requestId'], 'data': {
                        'context': '정렬된 배열에서 이진 탐색하는 수업',
                        'learning': [{'concept': '이진 탐색', 'explanation': '정렬 조건과 범위 축소',
                                      'evidence': question['evidence']}],
                        'types': [{'type': question['type'], 'reason': '조건 확인'}],
                        'questions': [question], 'shortageReason': 'fixture'}})
                prepared = session.call({'action': 'extract_batch',
                                         'batchRequestId': prepared['batchRequestId'], 'items': items})
            path = fixture.files.parent / 'study-sessions.db'
            with closing(sqlite3.connect(path)) as db:
                session = db.execute('SELECT state FROM study_sessions WHERE conversation=?', ('pipeline',)).fetchone()[0]
                pipeline_row = db.execute('SELECT state FROM study_pipelines WHERE user=? AND exam_id=?',
                                          ('fixture-user', 'conversation:pipeline')).fetchone()
            session_bytes = len(session.encode('utf-8'))
            pipeline_bytes = len(pipeline_row[0].encode('utf-8')) if pipeline_row else 0
            rows.append({'sessionStateBytes': session_bytes, 'pipelineStateBytes': pipeline_bytes,
                         'combinedStateBytes': session_bytes + pipeline_bytes})
        finally:
            fixture.tearDown()
            fixture.doCleanups()
    return {'status': 'measured', 'fixture': '4 text files, first extraction batch',
            'samples': rows, 'median': _median(rows)}


def _cache(repo: Path, samples: int):
    sys.path.insert(0, str(repo / 'skills/university-agent'))
    from features import material_cache
    rows = []
    with tempfile.TemporaryDirectory(prefix='turtleneck-cache-') as folder:
        root = Path(folder)
        material_cache.put(root, 'text', 'benchmark-user', 'shared', {'value': 'x' * 1000})
        def read(_index):
            value = material_cache.get(root, 'text', 'benchmark-user', 'shared')
            assert value['value'] == 'x' * 1000
        for _ in range(samples):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(read, range(40)))
            rows.append({'parallelReads': 40, 'workers': 4,
                         'elapsedMs': (time.perf_counter() - started) * 1000})
    return {'status': 'measured', 'samples': rows, 'median': _median(rows)}


def _media(repo: Path, samples: int):
    sys.path.insert(0, str(repo / 'skills/university-agent/tests'))
    sys.path.insert(0, str(repo / 'skills/university-agent'))
    from test_lecture_audio import SOURCE, Session
    from providers.lecture_media import download_media, media_plan
    rows = []
    for _ in range(samples):
        session = Session()
        plan = media_plan(session, SOURCE)
        with tempfile.TemporaryDirectory(prefix='turtleneck-media-') as folder:
            target = Path(folder) / 'media.bin'
            started = time.perf_counter()
            download_media(session, plan, target)
            elapsed = (time.perf_counter() - started) * 1000
            assert target.read_bytes() == b'GfirstGsecond'
        rows.append({'bytes': 14, 'elapsedMs': elapsed,
                     'requests': len(session.calls)})
    return {'status': 'measured', 'fixture': '2 MPEG-TS chunks, 14 bytes',
            'samples': rows, 'median': _median(rows)}


def _tls(repo: Path, samples: int):
    sys.path.insert(0, str(repo / 'skills/university-agent/tests'))
    sys.path.insert(0, str(repo / 'skills/university-agent/scripts'))
    sys.path.insert(0, str(repo / 'skills/university-agent'))
    from test_tls_optimization import fixture_pages, run_sync
    import sync_tls
    rows = []
    for index in range(samples):
        with tempfile.TemporaryDirectory(prefix='turtleneck-tls-') as folder:
            root = Path(folder)
            seed = root / 'seed.db'
            run_sync(sync_tls, fixture_pages(8), seed, '--full', '--metadata-only')
            case = root / 'case.db'
            case.write_bytes(seed.read_bytes())
            started = time.perf_counter()
            metrics = run_sync(sync_tls, fixture_pages(8), case, '--ensure', '--metadata-only')
            metrics['elapsedMs'] = (time.perf_counter() - started) * 1000
            metrics['sample'] = index
            rows.append(metrics)
    return {'status': 'measured', 'fixture': '8 courses, unchanged ensure refresh',
            'samples': rows, 'median': _median(rows)}


def _asr(repo: Path):
    return {'status': 'not_measured', 'reason': '실제 whisper.cpp 모델·GPU·전사 원본이 없는 오프라인 환경에서는 전사 시간을 추정하지 않음.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--commit', help='Commit label when --repo is an archive without .git')
    args = parser.parse_args()
    if args.samples < 1:
        raise SystemExit('--samples must be positive')
    repo = args.repo.resolve()
    started = _timestamp()
    result = {'benchmarkVersion': 1, 'run': {'startedAt': started, 'timezone': 'Asia/Seoul',
                                             'samplesRequested': args.samples},
              'environment': _environment(repo, args.commit),
              'parts': {name: {'role': meta['role'], 'files': meta['files']} for name, meta in PARTS.items()}}
    result['results'] = {}
    runners = {'study_pipeline': _study, 'study_storage': _study_storage, 'material_cache': _cache, 'lecture_media': _media,
               'tls_sync': _tls, 'local_asr': lambda _repo, _samples: _asr(_repo)}
    for name, runner in runners.items():
        missing = [path for path in PARTS[name]['files'] if not (repo / path).exists()]
        if missing:
            result['results'][name] = {'status': 'not_available', 'missingFiles': missing,
                                       'reason': '해당 상징 버전에는 이 파트가 아직 없어요.'}
            continue
        part_started = _timestamp()
        try:
            result['results'][name] = runner(repo, args.samples)
        except (ImportError, ModuleNotFoundError, AttributeError) as error:
            result['results'][name] = {'status': 'not_available', 'reason': str(error)}
        except ValueError as error:
            if 'no such test method' in str(error):
                result['results'][name] = {'status': 'not_available', 'reason': str(error)}
            else:
                raise
        result['results'][name]['startedAt'] = part_started
        result['results'][name]['finishedAt'] = _timestamp()
    result['run']['finishedAt'] = _timestamp()
    result['run']['durationSeconds'] = round((datetime.fromisoformat(result['run']['finishedAt']) -
                                              datetime.fromisoformat(started)).total_seconds(), 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'commit': result['environment']['commitShort'],
                      'logicalCores': result['environment']['logicalCores'],
                      'parts': {name: value['status'] for name, value in result['results'].items()}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
