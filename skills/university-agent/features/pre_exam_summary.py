"""Bounded, source-complete pre-exam summaries for weak host models."""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import re

from features import material_cache

VERSION = 'pre-exam-summary.v1'
CHUNK_CHARS = 12000
BATCH_SIZE = 2
LEVELS = ('critical', 'important', 'review', 'uncertain')
LEVEL_MARKERS = {'critical': '🔥', 'important': '⭐', 'review': '🔎', 'uncertain': '⚠️'}
REFERENCE_KINDS = {
    'everytime_review', 'student_report', 'ai_evaluation', 'internet_evaluation',
    'instructor_transcript', 'instructor_notice', 'notability_note', 'notability_transcript',
}
PROFESSOR_KINDS = {'instructor_transcript', 'instructor_notice', 'notability_note', 'notability_transcript'}


def _text(value, field, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{field}: 비어 있지 않은 문자열이 필요합니다.')
    return value.strip()


def _evidence(refs, sources):
    if not isinstance(refs, list) or not refs:
        raise ValueError('정리 항목에도 원문 근거가 필요합니다.')
    checked = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'resourceId', 'location', 'quote'}:
            raise ValueError('정리 근거 형식이 올바르지 않습니다.')
        source = next((item for item in sources if item.get('resourceId') == ref['resourceId']
                       and item.get('location') == ref['location']), None)
        quote = ref.get('quote')
        if not source or not isinstance(quote, str) or not quote.strip() or quote not in source.get('text', ''):
            raise ValueError('정리 근거가 선택한 자료 원문과 일치하지 않습니다.')
        checked.append({'resourceId': ref['resourceId'], 'location': ref['location'],
                        'quote': quote, 'name': source['name'], 'courseId': source['courseId']})
    return checked


def reference_sources(references, course_id):
    """Turn an explicitly selected note/transcript into a source, preserving provenance."""
    result = []
    for reference in references or []:
        if reference.get('kind') not in PROFESSOR_KINDS:
            continue
        identifier = 'attachment-' + material_cache.key(reference)[:16]
        result.append({'resourceId': identifier, 'courseId': course_id,
                       'name': reference['source'], 'location': reference['location'],
                       'text': reference['text'], 'sourceKind': reference['kind'],
                       'referenceId': reference.get('id')})
    return result


def _parts(sources):
    parts = []
    for source in sources:
        text = source.get('text', '')
        if not isinstance(text, str) or not text.strip():
            continue
        for index, start in enumerate(range(0, len(text), CHUNK_CHARS), 1):
            item = dict(source)
            item['text'] = text[start:start + CHUNK_CHARS]
            item['part'] = index
            item['partCount'] = (len(text) + CHUNK_CHARS - 1) // CHUNK_CHARS
            parts.append(item)
    return parts


def _schema():
    return {
        'summary': '이 자료 조각의 빠짐없는 핵심 흐름. 근거가 없으면 모른다고 표시',
        'coverage': [{
            'topic': '자료에 나온 주제',
            'points': ['주요 사실·정의·절차'],
            'definitions': ['용어와 의미'],
            'examples': ['자료에 나온 예시'],
            'evidence': [{'resourceId': 'SOURCE의 자료 ID', 'location': 'SOURCE의 위치', 'quote': '연속된 원문'}],
        }],
        'emphasis': [{
            'point': '특별히 다시 볼 내용',
            'level': 'critical|important|review|uncertain',
            'reason': '왜 표시했는지',
            'sourceKind': 'course_material|instructor_transcript|instructor_notice|notability_note|notability_transcript|other',
            'referenceId': '교수 자료이면 examReferences의 ID, 아니면 빈 문자열',
            'evidence': [{'resourceId': 'SOURCE의 자료 ID', 'location': 'SOURCE의 위치', 'quote': '연속된 원문'}],
        }],
        'gaps': ['읽을 수 없거나 근거가 부족해 확정하지 못한 내용'],
    }


def _request(part, index, total, course_name, references, focus_notes):
    request_id = f'summary-{index + 1}'
    return {
        'requestId': request_id,
        'sourceId': part['resourceId'],
        'location': part['location'],
        'part': part['part'],
        'partCount': part['partCount'],
        'instruction': (
            'SOURCE 한 조각만 근거로 고정 양식을 채우세요. 전체 내용을 빠뜨리지 않도록 주제별로 나누고, '
            '자료에 없는 사실은 만들지 마세요. 교수님 강조로 볼 수 있는 내용은 sourceKind와 referenceId를 '
            '정확히 표시하고, 단순 학생 후기·인터넷 평가는 교수님 강조로 분류하지 마세요. '
            '모든 coverage와 emphasis에는 SOURCE 안의 연속 원문 인용이 있어야 합니다. '
            'gaps는 빈 목록이어도 되지만 읽지 못한 부분이나 불확실한 부분은 반드시 적으세요.'
        ),
        'courseName': course_name,
        'progress': {'part': index + 1, 'totalParts': total},
        'examReferences': [{k: v for k, v in reference.items() if k != 'text'} for reference in references],
        'studyContext': focus_notes,
        'schema': _schema(),
        'SOURCE': [part],
    }


def start(session, state):
    course_id = state.get('selection', {}).get('courseId')
    references = state.get('examReferences', [])
    sources = list(state.get('sources', []))
    sources.extend(reference_sources(references, course_id))
    state['sources'] = sources
    parts = _parts(sources)
    if not parts:
        raise ValueError('정리할 수 있는 본문이 없습니다.')
    course_name = next((course['name'] for course in session.provider.get_courses(session.user)
                        if course['id'] == course_id), state.get('selection', {}).get('attachmentTitle', '첨부 자료'))
    requests = [_request(part, index, len(parts), course_name, references, state.get('focusNotes', []))
                for index, part in enumerate(parts)]
    state['summaryPipeline'] = {'version': VERSION, 'courseName': course_name,
                                'requests': requests, 'cursor': 0, 'parts': {}}
    state['phase'] = 'summary_extracting'
    return _next_batch(state)


def _next_batch(state):
    pipeline = state['summaryPipeline']
    start = pipeline['cursor']
    batch = pipeline['requests'][start:start + BATCH_SIZE]
    if not batch:
        result = assemble(state)
        state.update(phase='summary_finished', summary=result)
        return {'status': 'summary', 'summary': result, 'answer': '시험 전 정리본을 만들었어요. 🔥·⭐ 표시부터 확인해 보세요.'}
    return {
        'status': 'summary_extracting', 'needsSummaryExtraction': True,
        'summaryBatchRequestId': f"{state.get('requestId', 'summary')}-{start}",
        'progress': {'processedParts': start, 'totalParts': len(pipeline['requests']),
                     'processedSources': len(pipeline['parts']),
                     'totalSources': len({item['sourceId'] for item in pipeline['requests']})},
        'hostOnly': {'instruction': '각 요청의 SOURCE를 읽고 schema에 맞는 data를 반환하세요. 요청 밖의 내용을 보충하지 마세요.',
                     'requests': batch},
        'answer': f'자료를 빠짐없이 나누어 확인하는 중이에요 ({start}/{len(pipeline["requests"])}조각).',
    }


def validate_part(data, request):
    if not isinstance(data, dict):
        raise ValueError('정리 결과는 객체여야 합니다.')
    sources = request['SOURCE']
    summary = _text(data.get('summary'), 'summary', 6000)
    coverage = data.get('coverage')
    if not isinstance(coverage, list) or len(coverage) > 30:
        raise ValueError('자료 조각의 주제는 30개 이내여야 합니다.')
    checked_coverage = []
    for item in coverage:
        if not isinstance(item, dict) or set(item) - {'topic', 'points', 'definitions', 'examples', 'evidence'}:
            raise ValueError('정리 주제 형식이 올바르지 않습니다.')
        topic = _text(item.get('topic'), 'topic', 300)
        values = {}
        for key in ('points', 'definitions', 'examples'):
            raw = item.get(key, [])
            if not isinstance(raw, list) or len(raw) > 30 or any(not isinstance(v, str) or not v.strip() for v in raw):
                raise ValueError(f'{key} 형식이 올바르지 않습니다.')
            values[key] = [v.strip() for v in raw]
        values['topic'], values['evidence'] = topic, _evidence(item.get('evidence'), sources)
        checked_coverage.append(values)
    emphasis = data.get('emphasis', [])
    if not isinstance(emphasis, list) or len(emphasis) > 20:
        raise ValueError('강조 항목은 20개 이내여야 합니다.')
    checked_emphasis = []
    reference_ids = {item.get('id') for item in request.get('examReferences', [])}
    for item in emphasis:
        if not isinstance(item, dict) or set(item) - {'point', 'level', 'reason', 'sourceKind', 'referenceId', 'evidence'}:
            raise ValueError('강조 항목 형식이 올바르지 않습니다.')
        level = item.get('level')
        if level not in LEVELS:
            raise ValueError('강조 단계는 critical/important/review/uncertain 중 하나여야 합니다.')
        source_kind = item.get('sourceKind', 'course_material')
        if not isinstance(source_kind, str) or (source_kind not in REFERENCE_KINDS and source_kind not in {'course_material', 'other'}):
            raise ValueError('강조 출처 종류가 올바르지 않습니다.')
        reference_id = item.get('referenceId', '')
        if source_kind in PROFESSOR_KINDS and reference_id not in reference_ids:
            raise ValueError('교수님 강조로 표시한 항목에는 확인된 참고 자료 ID가 필요합니다.')
        checked_emphasis.append({'point': _text(item.get('point'), 'point', 600), 'level': level,
                                 'reason': _text(item.get('reason'), 'reason', 1000),
                                 'sourceKind': source_kind, 'referenceId': reference_id,
                                 'evidence': _evidence(item.get('evidence'), sources)})
    gaps = data.get('gaps', [])
    if not isinstance(gaps, list) or len(gaps) > 30 or any(not isinstance(item, str) or not item.strip() for item in gaps):
        raise ValueError('누락·불확실 항목 형식이 올바르지 않습니다.')
    return {'requestId': request['requestId'], 'sourceId': request['sourceId'], 'location': request['location'],
            'part': request['part'], 'summary': summary, 'coverage': checked_coverage,
            'emphasis': checked_emphasis, 'gaps': [item.strip() for item in gaps]}


def assemble(state):
    pipeline = state['summaryPipeline']
    parts = [pipeline['parts'][request['requestId']] for request in pipeline['requests']]
    emphasis = OrderedDict()
    coverage = []
    gaps = []
    for part in parts:
        source = next(item for item in pipeline['requests'] if item['requestId'] == part['requestId'])['SOURCE'][0]
        coverage.append({'source': {key: source[key] for key in ('resourceId', 'name', 'location')},
                         'part': part['part'], 'partCount': source['partCount'],
                         'summary': part['summary'], 'topics': part['coverage']})
        gaps.extend({'source': source['name'], 'location': source['location'], 'text': gap} for gap in part['gaps'])
        for item in part['emphasis']:
            key = re.sub(r'\s+', ' ', item['point']).strip().casefold()
            if key not in emphasis:
                emphasis[key] = {**item, 'marker': LEVEL_MARKERS[item['level']]}
            elif item['level'] == 'critical' and emphasis[key]['level'] != 'critical':
                emphasis[key].update(level='critical', marker=LEVEL_MARKERS['critical'])
    failures = state.get('failures', [])
    gaps.extend({'source': item['name'], 'location': '', 'text': item['reason']} for item in failures)
    professor = [item for item in emphasis.values() if item['sourceKind'] in PROFESSOR_KINDS]
    return {
        'schemaVersion': VERSION,
        'courseName': state['summaryPipeline'].get('courseName', '과목'),
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'coverage': {'complete': not failures, 'status': 'complete' if not gaps else 'complete_with_uncertainty',
                     'sourceCount': len({item['source']['resourceId'] for item in coverage}),
                     'partCount': len(coverage)},
        'sections': coverage,
        'professorEmphasis': professor,
        'emphasis': list(emphasis.values()),
        'omissions': gaps,
        'reviewChecklist': [{'marker': item['marker'], 'level': item['level'], 'point': item['point'],
                             'reason': item['reason']} for item in emphasis.values()],
    }


def handle(session, state, event):
    action = event.get('action')
    if action == 'summary_status':
        if state.get('phase') == 'summary_finished':
            return {'status': 'summary', 'summary': state['summary']}
        return _next_batch(state)
    if action != 'summary_extract' or state.get('phase') != 'summary_extracting':
        raise ValueError('시험 전 정리본의 현재 작업을 확인할 수 없습니다.')
    pipeline = state['summaryPipeline']
    start = pipeline['cursor']
    batch = pipeline['requests'][start:start + BATCH_SIZE]
    items = event.get('items')
    if not isinstance(items, list) or len(items) != len(batch):
        raise ValueError('현재 정리 작업의 모든 자료 조각을 한 번씩 보내야 합니다.')
    expected = {request['requestId']: request for request in batch}
    for item in items:
        if not isinstance(item, dict) or item.get('requestId') not in expected:
            raise ValueError('정리 자료 조각 ID가 일치하지 않습니다.')
        request = expected[item['requestId']]
        if item['requestId'] in pipeline['parts']:
            raise ValueError('이미 저장한 정리 자료 조각입니다.')
        pipeline['parts'][item['requestId']] = validate_part(item.get('data'), request)
    pipeline['cursor'] += len(batch)
    return _next_batch(state)
