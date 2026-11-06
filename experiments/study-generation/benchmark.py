"""Thirty-question local flow; deterministic host fixture, NOT measured AI latency."""
import argparse
import copy
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'skills/university-agent'), str(ROOT / 'skills/university-agent/tests')]
from test_study_pipeline import FilePipelineTests


def run(files):
    fixture = FilePipelineTests('test_chunk_boundaries_preserved_without_suffix_copy')
    fixture.setUp()
    try:
        for i in range(files):
            (fixture.files / f'{i}.txt').write_text('이진 탐색은 정렬된 배열에서 탐색한다.\n' * (4000 // files), encoding='utf-8')
        session = fixture.session('speed')
        calls = payload = extraction_rounds = parts = candidates = 0
        elapsed = 0
        def call(event):
            nonlocal calls, payload, elapsed
            start = time.perf_counter()
            result = session.call(event)
            elapsed += time.perf_counter() - start
            calls += 1
            payload += len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode())
            return result
        event = {'action': 'request', 'selection': {'courseId': 'course-1',
                 'resourceIds': [f'r{i}' for i in range(files)]}, 'settings': {'count': 30}}
        prepared = call(event)
        while prepared.get('needsExtraction'):
            items = []
            extraction_rounds += 1
            for host in prepared['hostOnly']['requests']:
                parts += 1
                q = fixture.candidate({'hostOnly': host})
                questions = []
                for i in range(host['settings']['count']):
                    item = copy.deepcopy(q)
                    candidates += 1
                    item.update(id=f'q{i}', question=item['question'] + f' 예제 {candidates}')
                    questions.append(item)
                items.append({'requestId': host['requestId'], 'data': {
                    'context': '정렬된 배열 탐색', 'learning': [{'concept': '이진 탐색',
                    'explanation': '정렬과 범위 축소', 'evidence': q['evidence']}],
                    'types': [{'type': q['type'], 'reason': '조건 확인'}], 'questions': questions}})
            prepared = call({'action': 'extract_batch', 'batchRequestId': prepared['batchRequestId'], 'items': items})
        ids = prepared['hostOnly']['selectionPlan']['candidateIds']
        assert len(ids) == 30
        reviewed = {q['id'] for q in prepared['hostOnly'].get('reviewQuestions', [])}
        missing = [cid for cid in ids if cid not in reviewed]
        for i in range(0, len(missing), 5):
            call({'action': 'candidate', 'candidateIds': missing[i:i+5]})
        assembled = call({'action': 'assemble', 'candidateIds': ids})
        assert assembled['needsWeb']
        cold = dict(local_ms=elapsed*1000, tool_calls=calls, extraction_rounds=extraction_rounds,
                    parts=parts, candidate_count=candidates, response_bytes=payload,
                    review_fetch_calls=(len(missing)+4)//5)
        calls = payload = 0
        elapsed = 0
        prepared = call(event)
        assert prepared.get('needsAssembly') and prepared['reusedFiles'] == files
        cold['warm_local_ms'] = elapsed*1000
        cold['warm_ai_extraction_rounds'] = 0
        return cold
    finally:
        fixture.tearDown()
        fixture.doCleanups()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=30)
    args = parser.parse_args()
    result = {'ai_latency_measured': False, 'questions': 30, 'samples': args.samples, 'scenarios': {}}
    for files in (1, 4):
        rows = [run(files) for _ in range(args.samples)]
        result['scenarios'][f'{files}_files'] = {'raw': rows,
            'median': {key: statistics.median(row[key] for row in rows) for key in rows[0]}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v['median'] for k, v in result['scenarios'].items()}, indent=2))
