"""Grounded assignment-draft contract: inspect requirements, confirm gaps, then write."""
from __future__ import annotations

VERSION = 'assignment-draft.v1'
PROFESSOR_KINDS = {'assignment_detail', 'instructor_notice', 'instructor_transcript', 'notability_note', 'notability_transcript'}


def _text(value, field, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{field}: 비어 있지 않은 문자열이 필요합니다.')
    return value.strip()


def _evidence(refs, sources):
    if not isinstance(refs, list) or not refs:
        raise ValueError('과제 조건에는 원문 근거가 필요합니다.')
    result = []
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'sourceId', 'location', 'quote'}:
            raise ValueError('과제 근거 형식이 올바르지 않습니다.')
        source = next((item for item in sources if item.get('sourceId') == ref['sourceId']
                       and item.get('location') == ref['location']), None)
        if not source or not isinstance(ref.get('quote'), str) or ref['quote'] not in source.get('text', ''):
            raise ValueError('과제 근거가 실제 자료와 일치하지 않습니다.')
        result.append({'sourceId': ref['sourceId'], 'location': ref['location'],
                       'quote': ref['quote'], 'sourceKind': source.get('sourceKind', 'course_material')})
    return result


def prepare(*, course_name: str, assignment: dict, sources: list[dict], user_answers: dict | None = None) -> dict:
    """Return the host-facing inspection contract; no draft is created here."""
    if not isinstance(sources, list) or not sources:
        raise ValueError('과제 조건을 확인할 자료가 없습니다.')
    normalized = [{'sourceId': str(item['sourceId']), 'location': str(item['location']),
                   'sourceKind': item.get('sourceKind', 'course_material'),
                   'text': str(item['text'])[:12000]} for item in sources]
    return {
        'schemaVersion': VERSION,
        'courseName': course_name,
        'assignment': {'title': assignment.get('title', ''), 'dueAt': assignment.get('dueAt'),
                       'url': assignment.get('url')},
        'userAnswers': user_answers or {},
        'questionsForUser': [
            '교수님이 댓글·수업·Notability에서 따로 강조한 조건이 있나요?',
            '제출 형식·분량·파일명·인용 규칙을 알고 있나요?',
            '답안에서 반드시 포함하거나 피하고 싶은 내용이 있나요?',
        ],
        'hostOnly': {
            'instruction': ('각 SOURCE와 userAnswers를 분리해 확인하세요. 먼저 professorChecks와 requirementChecks에 '
                            '확인된 조건을 적고, userAnswers로도 확인되지 않는 조건은 questionsForUser로 되돌리세요. '
                            '확인 전에는 최종 답안을 만들지 말고, 자료에 없는 조건은 추측하지 마세요.'),
            'schema': {
                'ready': 'boolean', 'title': '과제물 제목', 'format': '제출 형식', 'draft': '완성 초안',
                'requirementChecks': [{'requirement': '조건', 'status': 'confirmed|needs_user|not_found',
                                       'evidence': [{'sourceId': 'SOURCE ID', 'location': '위치', 'quote': '연속 원문'}]}],
                'professorChecks': [{'point': '교수님 강조점', 'confidence': 'confirmed|candidate|unknown',
                                     'evidence': [{'sourceId': 'SOURCE ID', 'location': '위치', 'quote': '연속 원문'}]}],
                'assumptions': ['사용자 확인 전 가정'],
                'missingQuestions': ['사용자에게 다시 확인할 질문'],
            },
            'SOURCE': normalized,
        },
    }


def sources_for_assignment(assignment: dict, notices: list[dict]) -> list[dict]:
    """Build bounded local sources; the host still decides what is relevant."""
    sources = []
    description = str(assignment.get('description') or '').strip()
    if description:
        sources.append({'sourceId': f"assignment-{assignment.get('externalId') or assignment.get('id')}",
                        'location': 'TLS 과제 상세', 'sourceKind': 'assignment_detail', 'text': description[:12000]})
    for item in notices:
        if item.get('courseId') != assignment.get('courseId'):
            continue
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        sources.append({'sourceId': str(item.get('id')), 'location': str(item.get('title') or 'TLS 공지'),
                        'sourceKind': 'instructor_notice', 'text': content[:12000]})
    return sources


def validate(data: dict, sources: list[dict]) -> dict:
    if not isinstance(data, dict) or type(data.get('ready')) is not bool:
        raise ValueError('과제 초안 결과와 ready 상태가 필요합니다.')
    checks = data.get('requirementChecks')
    if not isinstance(checks, list) or not checks:
        raise ValueError('과제 조건 확인 결과가 필요합니다.')
    checked = []
    for item in checks:
        if not isinstance(item, dict) or item.get('status') not in {'confirmed', 'needs_user', 'not_found'}:
            raise ValueError('과제 조건 상태가 올바르지 않습니다.')
        checked.append({'requirement': _text(item.get('requirement'), 'requirement', 500),
                        'status': item['status'], 'evidence': _evidence(item.get('evidence'), sources) if item['status'] != 'not_found' else []})
    professor = []
    for item in data.get('professorChecks', []):
        if not isinstance(item, dict) or item.get('confidence') not in {'confirmed', 'candidate', 'unknown'}:
            raise ValueError('교수님 강조점의 확신도 형식이 올바르지 않습니다.')
        evidence = _evidence(item.get('evidence'), sources) if item['confidence'] != 'unknown' else []
        professor.append({'point': _text(item.get('point'), 'point', 800), 'confidence': item['confidence'], 'evidence': evidence})
    missing = data.get('missingQuestions', [])
    if not isinstance(missing, list) or any(not isinstance(item, str) or not item.strip() for item in missing):
        raise ValueError('추가 확인 질문 형식이 올바르지 않습니다.')
    if data['ready'] and missing:
        raise ValueError('추가 확인 질문이 남은 초안은 ready로 표시할 수 없습니다.')
    if data['ready']:
        draft = _text(data.get('draft'), 'draft', 200000)
        title = _text(data.get('title'), 'title', 300)
    else:
        draft, title = '', str(data.get('title') or '과제 초안')[:300]
    assumptions = data.get('assumptions', [])
    if not isinstance(assumptions, list) or any(not isinstance(item, str) for item in assumptions):
        raise ValueError('가정 목록 형식이 올바르지 않습니다.')
    return {'schemaVersion': VERSION, 'ready': data['ready'], 'title': title, 'format': str(data.get('format') or '확인 필요'),
            'draft': draft, 'requirementChecks': checked, 'professorChecks': professor,
            'assumptions': assumptions[:20], 'missingQuestions': missing[:10]}


def format_result(result: dict) -> str:
    if not result.get('ready'):
        lines = ['### 과제 작성 전 확인', '- 아직 초안을 확정하지 않았어요.']
        for item in result.get('missingQuestions', [])[:3]:
            lines.append(f'- 확인할 내용: {item}')
        return '\n'.join(lines)
    lines = [f'### 과제 초안 · {result["title"]}', f'- 형식: {result["format"]}', '- 상태: ✅ 조건 확인 후 작성 완료']
    emphasized = [item['point'] for item in result.get('professorChecks', []) if item['confidence'] == 'confirmed']
    if emphasized:
        lines.append('- 교수님 강조: ' + ', '.join(emphasized[:3]))
    lines.append('\n' + result['draft'])
    return '\n'.join(lines)
