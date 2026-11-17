"""User-selected study-source contracts and safe routing metadata."""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from features.material_cache import key
from storage.private_files import atomic_write_text
from features.language import normalize_language


SOURCE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "notion",
        "name": "Notion",
        "kind": "workspace",
        "access": "user_connected_read_only",
        "consent": "notionContent",
        "content": ("pages", "blocks", "databases", "attachments"),
        "route": "notion",
        "status": "adapter_pending",
        "description": "페이지·블록·데이터베이스에 정리한 텍스트와 첨부자료",
    },
    {
        "id": "notability",
        "name": "Notability",
        "kind": "native_notes",
        "access": "local_read_only",
        "consent": "notabilityContent",
        "content": ("handwriting", "recordings", "transcripts", "pages"),
        "route": "notability-study",
        "status": "external_skill_available",
        "description": "필기·강의 녹음·전사·페이지 타임라인",
    },
    {
        "id": "goodnotes",
        "name": "Goodnotes",
        "kind": "exported_notes",
        "access": "explicit_file_import",
        "consent": "goodnotesContent",
        "content": ("pdf", "images"),
        "route": "document-import",
        "status": "export_only",
        "description": "사용자가 내보낸 PDF·이미지 노트",
    },
    {
        "id": "local_files",
        "name": "파일·폴더",
        "kind": "local_files",
        "access": "explicit_file_import",
        "consent": "sourceAnalysis",
        "content": ("pdf", "ppt", "docx", "hwp", "txt", "code"),
        "route": "document-import",
        "status": "available",
        "description": "사용자가 직접 고른 컴퓨터 안의 수업자료",
    },
)

_ALIASES = {
    "notion": "notion",
    "노션": "notion",
    "notability": "notability",
    "노타빌리티": "notability",
    "goodnotes": "goodnotes",
    "goodnotes앱": "goodnotes",
    "굿노트": "goodnotes",
    "파일": "local_files",
    "폴더": "local_files",
    "로컬": "local_files",
    "컴퓨터": "local_files",
}


def source_catalog() -> list[dict[str, Any]]:
    """Return model-safe source choices without paths, tokens or note contents."""
    return [{key: value for key, value in item.items() if key not in {"content"}}
            | {"content": list(item["content"])} for item in SOURCE_DEFINITIONS]


def normalize_source_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    known = {item["id"] for item in SOURCE_DEFINITIONS}
    for value in values:
        source_id = _ALIASES.get(str(value or "").strip().casefold(), str(value or "").strip())
        if source_id in known and source_id not in result:
            result.append(source_id)
    return result


def source_selection_answer() -> dict[str, Any]:
    return {
        "toolCalls": [],
        "needsLearningSourceSelection": True,
        "data": {"sources": source_catalog()},
        "answer": (
            "학습 내용을 어디에 저장해 두었는지 먼저 확인할게요. "
            "Notion은 페이지·블록 중심으로, Notability는 필기·녹음·전사 중심으로, "
            "Goodnotes는 사용자가 내보낸 PDF·이미지 중심으로 읽어요. "
            "주로 쓰는 곳을 하나 이상 골라 주세요. 선택하지 않은 앱은 열지 않아요."
        ),
    }


def normalize_document(value: dict) -> dict:
    """Common text contract used by source adapters, storage and study consumers."""
    allowed = {'schemaVersion', 'sourceId', 'sourceRef', 'title', 'courseId', 'sections', 'language', 'translatedFrom'}
    if not isinstance(value, dict) or set(value) - allowed or value.get('schemaVersion') != 1:
        raise ValueError('학습 자료는 schemaVersion 1의 공통 자료 형식으로 전달해 주세요.')
    if value.get('sourceId') not in {item['id'] for item in SOURCE_DEFINITIONS}:
        raise ValueError('확인된 학습 자료 출처를 지정해 주세요.')
    for field in ('sourceRef', 'title'):
        if not isinstance(value.get(field), str) or not value[field].strip() or len(value[field]) > 1000:
            raise ValueError('자료의 이름과 출처 식별값을 확인해 주세요.')
    # Source references are opaque IDs, never signed URLs or authentication fields.
    if any(marker in value['sourceRef'] for marker in ('?', '#', '://')):
        raise ValueError('sourceRef에는 URL 대신 페이지·노트·파일의 식별값만 넣어 주세요.')
    course_id = value.get('courseId', '')
    if 'language' in value:
        value = {**value, 'language': normalize_language(value['language'])}
    if 'translatedFrom' in value and (not isinstance(value['translatedFrom'], str) or
            not re.fullmatch(r'[a-f0-9]{64}', value['translatedFrom']) or not value.get('language')):
        raise ValueError('번역본에는 원문 자료 ID와 대상 언어를 함께 지정해 주세요.')
    if not isinstance(course_id, str) or len(course_id) > 200:
        raise ValueError('과목 식별값을 확인해 주세요.')
    sections = value.get('sections')
    if not isinstance(sections, list) or not 1 <= len(sections) <= 5000:
        raise ValueError('자료 본문은 위치가 있는 1~5000개 부분으로 전달해 주세요.')
    checked, locations, total = [], set(), 0
    for section in sections:
        if not isinstance(section, dict) or set(section) != {'location', 'text'}:
            raise ValueError('각 본문에는 location과 text만 넣어 주세요.')
        location, text = section['location'], section['text']
        if not isinstance(location, str) or not location.strip() or len(location) > 500 or location in locations:
            raise ValueError('본문 위치는 중복되지 않는 이름으로 지정해 주세요.')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('비어 있는 본문은 제외하고, 누락된 자료는 별도로 알려 주세요.')
        total += len(text)
        if total > 1_000_000:
            raise ValueError('자료를 100만 자 이하로 나눠 주세요.')
        checked.append({'location': location, 'text': text})
        locations.add(location)
    return {**value, 'courseId': course_id, 'sections': checked}


def _document_root(root: Path, user: str) -> Path:
    if not user:
        raise ValueError('자료를 저장할 학습 프로필을 먼저 선택해 주세요.')
    return Path(root) / 'source-documents' / key(user)


def save_document(root: Path, user: str, value: dict) -> dict:
    document = normalize_document(value)
    if document.get('translatedFrom'):
        original = load_document(root, user, document['translatedFrom'])
        if (document['sourceId'] != original['sourceId'] or document['sourceRef'] != original['sourceRef']
                or document['courseId'] != original['courseId']
                or [part['location'] for part in document['sections']] != [part['location'] for part in original['sections']]):
            raise ValueError('번역본의 출처·과목·본문 위치와 순서는 원문과 같아야 해요.')
    identifier = key(document)
    path = _document_root(root, user) / f'{identifier}.json'
    if not path.exists():
        atomic_write_text(path, json.dumps({**document, 'documentId': identifier,
            'savedAt': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
    return load_document(root, user, identifier)


def load_document(root: Path, user: str, identifier: str) -> dict:
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{64}', identifier):
        raise ValueError('저장된 자료 ID를 확인해 주세요.')
    path = _document_root(root, user) / f'{identifier}.json'
    if path.is_symlink() or path.stat().st_size > 8_000_000:
        raise ValueError('저장된 자료 파일을 확인해 주세요.')
    raw = json.loads(path.read_text(encoding='utf-8'))
    document = normalize_document({k: v for k, v in raw.items() if k not in {'documentId', 'savedAt'}})
    if key(document) != identifier or raw.get('documentId') != identifier:
        raise ValueError('자료 내용이 변경되었어요. 원본에서 다시 가져와 주세요.')
    return {**document, 'documentId': identifier, 'savedAt': raw['savedAt']}


def document_metadata(document: dict) -> dict:
    return {key: value for key, value in document.items() if key != 'sections'} | {
        'sectionCount': len(document['sections']),
        'characters': sum(len(section['text']) for section in document['sections'])}


def list_documents(root: Path, user: str, query: str = '') -> list[dict]:
    records = []
    for path in _document_root(root, user).glob('*.json'):
        record = load_document(root, user, path.stem)
        if query.casefold() in (record['title'] + ' ' + record['courseId']).casefold():
            records.append(document_metadata(record))
    return sorted(records, key=lambda item: item['savedAt'], reverse=True)


def document_material(root: Path, user: str, identifier: str) -> dict:
    document = load_document(root, user, identifier)
    return {'id': 'attachment-source-' + identifier, 'title': document['title'],
        'extension': 'txt', 'sourceKind': document['sourceId'], 'contentKey': identifier,
        'courseId': document['courseId'], 'sections': document['sections'], 'truncated': False}


def read_document(root: Path, user: str, identifier: str, *, section=0, text_offset=0) -> dict:
    document = load_document(root, user, identifier)
    if type(section) is not int or type(text_offset) is not int or not 0 <= section < len(document['sections']) or text_offset < 0:
        raise ValueError('본문 번호와 문자 위치를 확인해 주세요.')
    source = document['sections'][section]
    if text_offset >= len(source['text']):
        raise ValueError('본문 문자 범위를 벗어났어요.')
    text = source['text'][text_offset:text_offset + 12000]
    end = text_offset + len(text)
    next_part = ({'section': section, 'textOffset': end} if end < len(source['text']) else
                 {'section': section + 1, 'textOffset': 0} if section + 1 < len(document['sections']) else None)
    return {**document_metadata(document), 'section': section, 'location': source['location'],
        'textOffset': text_offset, 'text': text, 'next': next_part}
