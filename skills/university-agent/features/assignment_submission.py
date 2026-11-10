"""Observed-form assignment submission and compact Markdown confirmation."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re


_SECRET_QUERY = {'password', 'passwd', 'pwd', 'token', 'access_token', 'refresh_token', 'sesskey', 'secret'}


def safe_url(value: str) -> str:
    parts = urlsplit(value or '')
    query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True)
             if key.casefold() not in _SECRET_QUERY]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.current = None
        self.select = None
        self.textarea = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'form':
            self.current = {'action': values.get('action') or '', 'method': (values.get('method') or 'get').lower(),
                            'fields': {}, 'fileFields': [], 'textFields': [], 'buttons': []}
            self.forms.append(self.current)
        elif self.current is not None and tag == 'input':
            name = values.get('name') or ''
            kind = (values.get('type') or 'text').lower()
            if not name:
                return
            if kind == 'file':
                self.current['fileFields'].append(name)
            elif kind in {'submit', 'button', 'reset'}:
                self.current['buttons'].append({'name': name, 'value': values.get('value') or ''})
            elif kind not in {'radio', 'checkbox'} or 'checked' in values:
                self.current['fields'][name] = values.get('value') or ''
        elif self.current is not None and tag == 'textarea':
            self.textarea = values.get('name') or ''
            self.text = []
            if self.textarea:
                self.current['textFields'].append(self.textarea)
        elif self.current is not None and tag == 'select':
            self.select = values.get('name') or ''
        elif self.current is not None and tag == 'option' and self.select and 'selected' in values:
            self.current['fields'][self.select] = values.get('value') or ''

    def handle_data(self, data):
        if self.textarea:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'textarea' and self.current is not None and self.textarea:
            self.current['fields'][self.textarea] = ''.join(self.text)
            self.textarea = None
        elif tag == 'select':
            self.select = None
        elif tag == 'form':
            self.current = None


def forms(html: str) -> list[dict]:
    parser = _FormParser()
    parser.feed(html or '')
    return parser.forms


def _is_assignment_form(form: dict) -> bool:
    action = form.get('action', '')
    fields = form.get('fields', {})
    names = set(fields) | set(form.get('fileFields', [])) | set(form.get('textFields', []))
    return ('/mod/assign/' in action or fields.get('id')) and (
        'action' in fields or any(name.startswith('assignsubmission_') for name in names))


def find_submission_form(html: str) -> dict:
    candidates = [form for form in forms(html) if _is_assignment_form(form)]
    draft = next((form for form in candidates if form['fields'].get('action') in {'editsubmission', 'savesubmission'}
                  or form['fileFields'] or form['textFields']), None)
    final = next((form for form in candidates if form['fields'].get('action') in {'submit', 'confirm'}
                  or any(re.search(r'제출|submit|grading', button['value'], re.I) for button in form['buttons'])), None)
    if not draft and not final:
        raise ValueError('현재 과제 화면에서 확인된 제출 양식을 찾지 못했어요.')
    return {'draft': draft, 'final': final}


def inspect(html: str, page_url: str) -> dict:
    found = find_submission_form(html)
    draft = found['draft'] or {}
    final = found['final'] or {}
    text_fields = [name for name in draft.get('textFields', []) if 'editor' in name or 'text' in name]
    file_fields = list(draft.get('fileFields', []))
    file_manager_fields = [name for name in draft.get('fields', {}) if 'filemanager' in name]
    return {'assignmentUrl': safe_url(page_url), 'draftAction': safe_url(draft.get('action', '')),
            'finalAction': safe_url(final.get('action', '')), 'textFields': text_fields,
            'fileFields': file_fields, 'fileManagerFields': file_manager_fields,
            'finalButtons': [button['value'] for button in final.get('buttons', [])],
            'supportsText': bool(text_fields), 'supportsDirectFile': bool(file_fields),
            'supportsFileManager': bool(file_manager_fields)}


def page_text(html: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()


def confirmed(html: str) -> bool:
    text = page_text(html)
    return bool(re.search(r'제출\s*(?:완료|됨)|Submitted\s+for\s+grading|Submission\s+status\s*:\s*Submitted', text, re.I))


def submission_result(*, course: str, title: str, status: str, page_url: str,
                     files: list[str] | None = None, verified: bool = False, detail: str = '') -> dict:
    return {'course': course or '과목 확인 필요', 'assignment': title or '과제', 'status': status,
            'files': list(files or []), 'verified': bool(verified), 'url': safe_url(page_url), 'detail': detail}


def format_submission_result(result: dict) -> str:
    icon = '✅' if result.get('verified') else '⚠️'
    lines = [f'### 과제 제출 {"확인" if result.get("verified") else "결과"}',
             f'- 과목: {result.get("course") or "확인 필요"}',
             f'- 과제: {result.get("assignment") or "확인 필요"}',
             f'- 상태: {icon} {result.get("status") or "확인 필요"}']
    files = result.get('files') or []
    if files:
        lines.append('- 제출 파일: ' + ', '.join(f'`{name}`' for name in files))
    if result.get('url'):
        lines.append(f'- [TLS에서 확인하기]({result["url"]})')
    if result.get('detail'):
        lines.append(f'- 참고: {result["detail"]}')
    return '\n'.join(lines)
