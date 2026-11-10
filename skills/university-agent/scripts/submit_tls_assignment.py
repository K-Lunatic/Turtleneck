#!/usr/bin/env python3
"""Submit one TLS assignment only through the form observed on its page."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.assignment_submission import confirmed, find_submission_form, format_submission_result, inspect, page_text, submission_result
from providers.credentials import CredentialInputRequired
from providers.moodle_session import LoginError
from providers.tls_auth import authenticated_session


class AssignmentSubmissionError(ValueError):
    pass


def _assignment_id(value: str) -> str:
    match = re.fullmatch(r'(?:tls-assignment-)?([1-9][0-9]*)', value.strip())
    if not match:
        raise AssignmentSubmissionError('TLS 과제 ID는 확인된 숫자 ID여야 합니다.')
    return match.group(1)


def _safe_action(session, page_url: str, action: str) -> str:
    url = urljoin(page_url, action)
    parts, base = urlsplit(url), urlsplit(session.base_url)
    if (parts.scheme, parts.hostname, parts.port or 443) != (base.scheme, base.hostname, base.port or 443):
        raise AssignmentSubmissionError('제출 양식의 주소가 학교 주소와 달라 중단했어요.')
    return parts.path + (f'?{parts.query}' if parts.query else '')


def _button(form: dict, pattern: str) -> tuple[str, str]:
    for button in form.get('buttons', []):
        if re.search(pattern, button.get('value', ''), re.I):
            return button['name'] or 'submitbutton', button['value'] or '저장'
    buttons = form.get('buttons', [])
    if buttons:
        button = buttons[0]
        return button['name'] or 'submitbutton', button['value'] or '저장'
    return 'submitbutton', '저장'


def _filemanager_config(html: str) -> dict:
    marker = next((item for item in ('M.form_filemanager.init', 'M.form_filepicker.init') if item in html), None)
    if not marker:
        raise AssignmentSubmissionError('TLS 파일 선택기 설정을 확인하지 못했어요.')
    start = html.find('{', html.find(marker))
    if start < 0:
        raise AssignmentSubmissionError('TLS 파일 선택기 설정이 비어 있어요.')
    depth, quote, escaped = 0, None, False
    end = None
    for index in range(start, len(html)):
        char = html[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        raise AssignmentSubmissionError('TLS 파일 선택기 설정을 끝까지 읽지 못했어요.')
    try:
        value = json.loads(html[start:end])
    except json.JSONDecodeError as error:
        raise AssignmentSubmissionError('TLS 파일 선택기 설정 형식이 달라요.') from error
    if not isinstance(value, dict):
        raise AssignmentSubmissionError('TLS 파일 선택기 설정이 올바르지 않아요.')
    return value


def _upload_file(session, page_url: str, html: str, form: dict, path: Path) -> str:
    config = _filemanager_config(html)
    options = config.get('options') if isinstance(config.get('options'), dict) else {}
    item_id = config.get('itemid') or options.get('itemid')
    client_id = config.get('client_id') or options.get('client_id')
    repositories = config.get('repositories') or options.get('repositories')
    repo_id = next((key for key, value in (repositories or {}).items()
                    if isinstance(value, dict) and value.get('type') == 'upload'), None)
    sesskey = form.get('fields', {}).get('sesskey')
    match = re.search(r'(?:(?:https?:)?//[^"\']+)?(/repository/repository_ajax\.php)', html)
    if not item_id or not client_id or not repo_id or not sesskey or not match:
        raise AssignmentSubmissionError('TLS 파일 업로드에 필요한 실제 선택기 정보가 부족해요.')
    from scripts.restore_moodle_backup import _multipart
    payload, content_type = _multipart({
        'action': 'upload', 'repo_id': str(repo_id), 'itemid': str(item_id),
        'sesskey': str(sesskey), 'client_id': str(client_id), 'savepath': '/',
    }, 'repo_upload_file', path)
    response, _ = session.post_bytes(match.group(1), payload, content_type=content_type,
                                     referer=page_url, allowed_origin=urlsplit(session.base_url).hostname)
    try:
        result = json.loads(response)
    except json.JSONDecodeError as error:
        raise AssignmentSubmissionError('TLS 파일 업로드 응답을 읽지 못했어요.') from error
    if not isinstance(result, dict) or result.get('error'):
        raise AssignmentSubmissionError('TLS가 과제 파일 업로드를 거부했어요.')
    return str(item_id)


def _post_form(session, page_url: str, form: dict, overrides: dict[str, str], button_pattern: str,
               file_path: Path | None = None) -> tuple[str, str]:
    fields = dict(form.get('fields', {}))
    fields.update(overrides)
    name, value = _button(form, button_pattern)
    fields[name] = value
    action = _safe_action(session, page_url, form.get('action', ''))
    if file_path:
        from scripts.restore_moodle_backup import _multipart
        field = form.get('fileFields', [None])[0]
        if not field:
            raise AssignmentSubmissionError('제출 파일 입력 칸을 확인하지 못했어요.')
        body, content_type = _multipart(fields, field, file_path)
        return session.post_bytes(action, body, content_type=content_type, referer=page_url,
                                  allowed_origin=urlsplit(session.base_url).hostname)
    return session._request(action, data=urlencode(fields, doseq=True).encode(), referer=page_url)


def inspect_assignment(assignment_id: str) -> dict:
    _, session = authenticated_session()
    page_url = urljoin(session.base_url.rstrip('/') + '/', f'mod/assign/view.php?id={_assignment_id(assignment_id)}')
    html, page_url = session.get_page(page_url)
    return inspect(html, page_url)


def submit(assignment_id: str, *, file_path: Path | None = None, text: str | None = None,
           apply: bool = False, confirm_word: str = '', course: str = '') -> dict:
    if file_path is None and not (isinstance(text, str) and text.strip()):
        raise AssignmentSubmissionError('제출할 파일 또는 본문을 하나 이상 지정해 주세요.')
    if file_path is not None:
        file_path = file_path.expanduser().resolve(strict=True)
        if not file_path.is_file() or file_path.stat().st_size > 100_000_000:
            raise AssignmentSubmissionError('제출 파일은 100MB 이하의 실제 파일이어야 합니다.')
    if apply and confirm_word != '제출':
        raise AssignmentSubmissionError('실제 제출은 --confirm 제출을 함께 지정해야 합니다.')
    _, session = authenticated_session()
    page_url = urljoin(session.base_url.rstrip('/') + '/', f'mod/assign/view.php?id={_assignment_id(assignment_id)}')
    html, page_url = session.get_page(page_url)
    found = find_submission_form(html)
    draft = found.get('draft')
    if not draft:
        raise AssignmentSubmissionError('현재 과제에서 답안 작성 양식을 찾지 못했어요.')
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', title_match.group(1))).strip() if title_match else 'TLS 과제'
    form_info = inspect(html, page_url)
    if file_path and not (form_info['supportsDirectFile'] or form_info['supportsFileManager']):
        raise AssignmentSubmissionError('이 과제의 파일 선택기 양식을 아직 확인하지 못했어요. 제출하지 않았습니다.')
    if text and not form_info['supportsText']:
        raise AssignmentSubmissionError('이 과제의 온라인 본문 입력 양식을 아직 확인하지 못했어요. 제출하지 않았습니다.')
    overrides = {}
    if text:
        overrides[form_info['textFields'][0]] = text
    if not apply:
        result = submission_result(course=course, title=title, status='제출 전 확인', page_url=page_url,
                                   files=[file_path.name] if file_path else [], detail='실제 제출은 실행하지 않았어요.')
        result['form'] = form_info
        return result
    if file_path and form_info['supportsFileManager']:
        item_id = _upload_file(session, page_url, html, draft, file_path)
        overrides[form_info['fileManagerFields'][0]] = item_id
    html, page_url = _post_form(session, page_url, draft, overrides, r'저장|save|제출|submit',
                                file_path if file_path and form_info['supportsDirectFile'] else None)
    html, page_url = session.get_page(page_url)
    final = find_submission_form(html).get('final')
    if final:
        html, page_url = _post_form(session, page_url, final, {}, r'제출|submit|grading')
        html, page_url = session.get_page(page_url)
    verified = confirmed(html)
    filename = file_path.name if file_path else None
    file_verified = not filename or filename in page_text(html)
    result = submission_result(course=course, title=title,
                               status='제출 완료' if verified else '제출 상태 확인 필요', page_url=page_url,
                               files=[filename] if filename and file_verified else [], verified=verified and file_verified,
                               detail='' if verified and file_verified else 'TLS 화면에서 최종 상태나 파일명을 다시 확인해 주세요.')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='관찰된 TLS 과제 제출 양식으로 한 과제 제출')
    parser.add_argument('--assignment-id', required=True)
    parser.add_argument('--file', type=Path)
    parser.add_argument('--text')
    parser.add_argument('--course', default='')
    parser.add_argument('--inspect', action='store_true', help='제출하지 않고 현재 양식만 확인')
    parser.add_argument('--apply', action='store_true', help='실제 제출 실행')
    parser.add_argument('--confirm', default='', help='실제 제출 확인 문구: 제출')
    args = parser.parse_args()
    try:
        result = inspect_assignment(args.assignment_id) if args.inspect else submit(
            _assignment_id(args.assignment_id), file_path=args.file, text=args.text,
            apply=args.apply, confirm_word=args.confirm, course=args.course)
        if args.inspect:
            result['status'] = '제출 양식 확인'
        print(json.dumps({'toolCalls': ['submit_tls_assignment'], 'data': result,
                          'answer': format_submission_result(result)}, ensure_ascii=False, separators=(',', ':')))
    except (AssignmentSubmissionError, CredentialInputRequired, LoginError, OSError, ValueError) as error:
        print(json.dumps({'toolCalls': ['submit_tls_assignment'], 'data': {'performed': False},
                          'error': {'code': 'TLS_ASSIGNMENT_SUBMISSION_FAILED', 'message': str(error)},
                          'answer': str(error)}, ensure_ascii=False, separators=(',', ':')))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
