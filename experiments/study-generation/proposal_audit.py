"""Offline size-only audit of a proposed handoff; production protocol is unchanged."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'skills/university-agent'), str(ROOT / 'skills/university-agent/tests')]
from test_study_pipeline import FilePipelineTests


def size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())


def audit(chars):
    fixture = FilePipelineTests('test_chunk_boundaries_preserved_without_suffix_copy')
    fixture.setUp()
    try:
        (fixture.files / '0.txt').write_text('가' * chars, encoding='utf-8')
        result = fixture.session('proposal').call({'action': 'request',
            'selection': {'courseId': 'course-1', 'resourceIds': ['r0']},
            'settings': {'count': 30, 'types': ['mcq'] * 30}})
        old = result['hostOnly']
        proposed = {**result, 'hostOnly': {'requests': old['requests'], 'batchRequestId': old['batchRequestId']}}
        assert old['SOURCE'] == old['requests'][0]['SOURCE']
        assert old['requests'] == proposed['hostOnly']['requests']
        assert sum(len(s['text']) for r in old['requests'] for s in r['SOURCE']) == chars
        return {'synthetic_source_chars': chars, 'requests': len(old['requests']),
            'current_response_bytes': size(result), 'proposed_response_bytes': size(proposed),
            'response_byte_reduction_percent': round((1-size(proposed)/size(result))*100, 3),
            'all_request_sources_preserved': True, 'ai_latency_measured': False,
            'legacy_root_consumers_need_migration': True}
    finally:
        fixture.tearDown()
        fixture.doCleanups()


if __name__ == '__main__':
    live = json.loads((Path(__file__).parent / 'results/live-java.json').read_text(encoding='utf-8'))
    row = live['compact_live_sample']
    wall = row['request_to_web_api_seconds']
    local = sum(event['localSeconds'] for event in row['events'])
    result = {'scope': 'Planning audit only; no production code or model configuration changed.',
        'observed_web_seconds': wall, 'observed_local_call_seconds': local,
        'seconds_if_local_calls_were_free': wall-local,
        'required_reduction': {str(target): {'seconds': wall-target,
            'percent': round((1-target/wall)*100, 3)} for target in (60, 45, 30)},
        'synthetic_protocol_examples': [audit(7703), audit(20000)]}
    out = Path(__file__).parent / 'results/next-proposal-audit.json'
    out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
