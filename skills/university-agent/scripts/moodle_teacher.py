#!/usr/bin/env python3
"""Plan-first Moodle instructor tools: capabilities, grading, submissions and materials."""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.moodle_teaching import (_links, inspect_grading_form, inspect_teacher_capabilities,
                                      observed_submission_files, save_submission_bytes, submission_plan)
from providers.credentials import CredentialInputRequired
from providers.moodle_provider import MoodleTLSProvider, _header_filename, autonomous_management_role
from providers.moodle_session import LoginError, MoodleSession
from providers.tls_auth import authenticated_session
from scripts.inspect_tls_activity_forms import _FormParser


class TeacherToolError(ValueError):
    pass


def _id(value: str, label: str) -> str:
    value = value.removeprefix('tls-').removeprefix('moodle-')
    if not re.fullmatch(r'[1-9][0-9]*', value):
        raise TeacherToolError(f'{label}는 확인된 숫자 ID여야 해요.')
    return value


def _host(session: MoodleSession) -> str:
    return urlsplit(session.base_url).hostname or ''


def _session() -> tuple[str, MoodleSession]:
    return authenticated_session()


def _autonomous_status(session: MoodleSession, username: str, course_id: str) -> dict[str, object]:
    external_id = _id(course_id, '강좌 ID')
    course = next((item for item in MoodleTLSProvider(session).get_autonomous_courses(username)
                   if str(item.get('externalId')) == external_id), None)
    if course is None:
        return {'matched': False, 'courseId': external_id, 'ownerRoleVisible': False,
                'reason': '현재 계정의 자율강좌 목록에서 해당 강좌를 찾지 못했어요.'}
    owner = autonomous_management_role(str(course.get('role') or '')) and course.get('ownerControlsVisible') is True
    return {'matched': True, 'courseId': external_id, 'courseName': course.get('name'),
            'role': course.get('role'), 'ownerControlsVisible': bool(course.get('ownerControlsVisible')),
            'ownerRoleVisible': owner,
            'reason': None if owner else '자율강좌 운영 권한과 수정 표시를 함께 확인하지 못했어요.'}


def _require_autonomous(status: dict[str, object]) -> None:
    if not status.get('ownerRoleVisible'):
        raise TeacherToolError(str(status.get('reason') or '자율강좌 운영 권한을 확인하지 못했어요.'))


def _autonomous_not_checked() -> dict[str, object]:
    return {'checked': False, 'reason': '자율강좌 전용 검증을 선택하지 않았어요.'}


def _course_page(session: MoodleSession, course_id: str) -> tuple[str, str]:
    return session.get_page(f'/course/view.php?id={_id(course_id, "강좌 ID")}')


def _assignment_page(session: MoodleSession, assignment_id: str) -> tuple[str, str]:
    return session.get_page(f'/mod/assign/view.php?id={_id(assignment_id, "과제 ID")}')


def _grading_page(session: MoodleSession, assignment_id: str) -> tuple[str, str, dict[str, object]]:
    html, page_url = _assignment_page(session, assignment_id)
    capability = inspect_teacher_capabilities(html, session.base_url)
    links = _links(html, page_url)
    target = None
    for link in links:
        url = link['url']
        path, query = urlsplit(url).path, urlsplit(url).query
        if '/mod/assign/' in path and ('grading' in path or 'action=grading' in query or
                                       re.search(r'채점|성적|grade|submission', link['text'], re.I)):
            target = url
            break
    if not target:
        raise TeacherToolError('교수용 과제 채점 화면의 실제 링크를 찾지 못했어요. 학생 권한이거나 화면 구성이 다른 Moodle일 수 있어요.')
    grading_html, grading_url = session.get_page(target)
    grading_capability = inspect_teacher_capabilities(grading_html, session.base_url)
    if not grading_capability['capabilities']['bulkGrading']:
        # The standard grading fields are stronger evidence than a translated link label.
        form = inspect_grading_form(grading_html, session.base_url)
        if not form['available']:
            raise TeacherToolError('채점 화면은 열렸지만 학생별 점수 입력 양식을 확인하지 못했어요.')
        observed_capabilities = dict(grading_capability['capabilities'])
        observed_capabilities.update({'bulkGrading': True, 'submissionDownload': True})
        grading_capability = {
            **grading_capability,
            'role': 'teacher_or_manager',
            'capabilities': observed_capabilities,
            'evidence': sorted(set(grading_capability['evidence']) | {'observed_grading_form'}),
            'verifiedBy': 'visible_same_origin_links_and_grading_form',
        }
    return grading_html, grading_url, {**capability, **grading_capability}


def capabilities(course_id: str, *, autonomous_only: bool = False) -> dict[str, object]:
    username, session = _session()
    autonomous = _autonomous_status(session, username, course_id) if autonomous_only else _autonomous_not_checked()
    html, page_url = _course_page(session, course_id)
    result = inspect_teacher_capabilities(html, session.base_url)
    return {'courseId': _id(course_id, '강좌 ID'), 'page': urlsplit(page_url).path, **result,
            'autonomousCourse': autonomous,
            'writes': 'disabled', 'message': '화면에 실제 교수용 관리 링크가 보인 경우에만 다음 단계를 열어요.'}


def submission_download(assignment_id: str, output: Path, template: str, *, apply: bool, confirm: str,
                        overwrite: bool = False) -> dict[str, object]:
    _username, session = _session()
    html, page_url, capability = _grading_page(session, assignment_id)
    if not capability['capabilities']['submissionDownload']:
        raise TeacherToolError('이 계정에서 제출물 일괄 열람 권한을 확인하지 못했어요.')
    files = observed_submission_files(html, session.base_url)
    plan = submission_plan(files, assignment=_id(assignment_id, '과제 ID'), template=template)
    result: dict[str, object] = {'assignmentId': _id(assignment_id, '과제 ID'), 'mode': 'apply' if apply else 'plan',
                                 'page': urlsplit(page_url).path, 'capabilities': capability, 'files': plan}
    if not apply:
        return result
    expected_confirmation = '다운로드 기존파일 덮어쓰기' if overwrite else '다운로드'
    if confirm != expected_confirmation:
        message = ('기존 파일을 덮어쓰려면 --confirm "다운로드 기존파일 덮어쓰기"가 필요해요.'
                   if overwrite else '실제 제출물 저장은 --confirm 다운로드를 함께 지정해야 해요.')
        raise TeacherToolError(message)
    saved = []
    for item in plan:
        content, response = session.get_bytes(item['source'], allowed_origin=_host(session))
        if not content:
            raise TeacherToolError(f'빈 제출물 응답이라 저장을 멈췄어요: {item["filename"]}')
        response_name = _header_filename(response.headers)
        target_name = item['filename'] if not response_name else submission_plan(
            [{'url': item['source'], 'label': item.get('label', ''), 'filename': response_name}],
            assignment=_id(assignment_id, '과제 ID'), template=template)[0]['filename']
        target = save_submission_bytes(output, target_name, content, overwrite=overwrite)
        saved.append({'filename': target.name, 'path': str(target), 'bytes': len(content)})
    result['files'] = saved
    return result


def _grade_fields(html: str) -> tuple[str, dict[str, str], dict[str, str]]:
    for form in re.finditer(r'<form\b([^>]*)>(.*?)</form>', html, re.I | re.S):
        attrs, body = form.groups()
        student_ids = sorted(set(re.findall(r'\bname=["\']grade\[([1-9][0-9]*)\]["\']', body, re.I)))
        if not student_ids:
            continue
        action_match = re.search(r'\baction=["\']([^"\']*)["\']', attrs, re.I)
        action = unescape(action_match.group(1)) if action_match else ''
        hidden = {}
        for tag in re.findall(r'<input\b[^>]*>', body, re.I):
            name = re.search(r'\bname=["\']([^"\']+)["\']', tag, re.I)
            value = re.search(r'\bvalue=["\']([^"\']*)["\']', tag, re.I)
            if name and value and not re.search(r'\btype=["\'](?:submit|button|reset)["\']', tag, re.I):
                hidden[name.group(1)] = unescape(value.group(1))
        fields = {student_id: hidden.get(f'grade[{student_id}]', '') for student_id in student_ids}
        return action, hidden, fields
    raise TeacherToolError('채점 양식을 찾지 못했어요.')


def grade(assignment_id: str, grades_path: Path, *, apply: bool, confirm: str) -> dict[str, object]:
    try:
        grades = json.loads(grades_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise TeacherToolError('점수 계획 파일을 읽지 못했어요.') from error
    if not isinstance(grades, dict) or not grades or any(not re.fullmatch(r'[1-9][0-9]*', str(key)) for key in grades):
        raise TeacherToolError('점수 계획은 학생 숫자 ID를 키로 가진 객체여야 해요.')
    if any(not isinstance(value, (int, float)) or value < 0 or value > 100 for value in grades.values()):
        raise TeacherToolError('점수는 0~100 사이 숫자여야 해요.')
    _username, session = _session()
    html, page_url, capability = _grading_page(session, assignment_id)
    action, hidden, fields = _grade_fields(html)
    if not fields or any(str(key) not in fields for key in grades):
        raise TeacherToolError('계획에 포함된 학생이 현재 채점 화면에 없어 저장하지 않았어요.')
    action_url = urljoin(page_url, action)
    action_parts = urlsplit(action_url)
    base_parts = urlsplit(session.base_url)
    if (action_parts.scheme, action_parts.hostname, action_parts.port or 443) != (base_parts.scheme, _host(session), base_parts.port or 443):
        raise TeacherToolError('채점 양식의 저장 주소가 학교 주소와 달라 중단했어요.')
    result = {'assignmentId': _id(assignment_id, '과제 ID'), 'mode': 'apply' if apply else 'plan',
              'studentCount': len(grades), 'screenStudentCount': len(fields), 'capabilities': capability,
              'formAction': urlsplit(action_url).path}
    if not apply:
        return result
    if confirm != '채점':
        raise TeacherToolError('실제 점수 저장은 --confirm 채점을 함께 지정해야 해요.')
    payload = dict(hidden)
    payload.update({f'grade[{key}]': str(value) for key, value in grades.items()})
    html, response = session._request(urlsplit(action_url).path + (f'?{urlsplit(action_url).query}' if urlsplit(action_url).query else ''),
                                      data=urlencode(payload, doseq=True).encode(), referer=page_url)
    if re.search(r'name=["\']username["\']|/login', response.geturl(), re.I) or re.search(r'alert-danger|error', html, re.I):
        raise TeacherToolError('Moodle가 점수 저장 후 오류 화면을 반환했어요. 결과를 성공으로 처리하지 않았어요.')
    result['status'] = 'submitted_to_observed_form'
    return result


def inspect_material(course_id: str, section: str, *, autonomous_only: bool = False) -> dict[str, object]:
    username, session = _session()
    autonomous = _autonomous_status(session, username, course_id) if autonomous_only else _autonomous_not_checked()
    course_html, page_url = _course_page(session, course_id)
    capability = inspect_teacher_capabilities(course_html, session.base_url)
    if not capability['capabilities']['materialUpload']:
        raise TeacherToolError('이 강좌에서 교수용 자료 관리 링크를 확인하지 못했어요.')
    course_id = _id(course_id, '강좌 ID')
    if not re.fullmatch(r'[1-9][0-9]*', section):
        raise TeacherToolError('토픽 번호는 확인된 숫자여야 해요.')
    html, form_url = session.get_page(f'/course/modedit.php?course={course_id}&section={section}&add=resource')
    parser = _FormParser()
    parser.feed(html)
    action = urlsplit(urljoin(form_url, parser.action))
    if action.hostname != _host(session) or action.path != '/course/modedit.php' or parser.method != 'POST':
        raise TeacherToolError('자료 추가 양식의 실제 저장 주소를 확인하지 못했어요.')
    return {'courseId': course_id, 'section': section, 'mode': 'plan', 'page': urlsplit(form_url).path,
            'formAction': action.path, 'fieldNames': sorted(parser.fields),
            'fileFields': sorted(name for name, item in parser.fields.items() if item['kind'] == 'file'),
            'capabilities': capability, 'autonomousCourse': autonomous, 'writes': 'disabled'}


def main():
    parser = argparse.ArgumentParser(description='Moodle 교수용 기능: 권한 확인, 제출물, 채점, 자료 양식')
    sub = parser.add_subparsers(dest='command', required=True)
    item = sub.add_parser('capabilities'); item.add_argument('--course-id', required=True); item.add_argument('--autonomous-only', action='store_true')
    item = sub.add_parser('download-submissions'); item.add_argument('--assignment-id', required=True); item.add_argument('--output', type=Path, required=True); item.add_argument('--name-template', default='{index:03d}_{filename}'); item.add_argument('--apply', action='store_true'); item.add_argument('--confirm', default=''); item.add_argument('--overwrite', action='store_true')
    item = sub.add_parser('inspect-grading'); item.add_argument('--assignment-id', required=True)
    item = sub.add_parser('grade'); item.add_argument('--assignment-id', required=True); item.add_argument('--grades', type=Path, required=True); item.add_argument('--apply', action='store_true'); item.add_argument('--confirm', default='')
    item = sub.add_parser('inspect-material'); item.add_argument('--course-id', required=True); item.add_argument('--section', required=True); item.add_argument('--autonomous-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'capabilities': result = capabilities(args.course_id, autonomous_only=args.autonomous_only)
    elif args.command == 'download-submissions': result = submission_download(args.assignment_id, args.output, args.name_template, apply=args.apply, confirm=args.confirm, overwrite=args.overwrite)
    elif args.command == 'inspect-grading':
        _username, session = _session(); html, page_url, capability = _grading_page(session, args.assignment_id)
        result = {'assignmentId': _id(args.assignment_id, '과제 ID'), 'page': urlsplit(page_url).path, 'form': inspect_grading_form(html, session.base_url), 'capabilities': capability, 'writes': 'disabled'}
    elif args.command == 'grade': result = grade(args.assignment_id, args.grades, apply=args.apply, confirm=args.confirm)
    else: result = inspect_material(args.course_id, args.section, autonomous_only=args.autonomous_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except PermissionError as error:
        raise SystemExit('이 환경에서 학교 로그인 화면을 열 수 없어요. 별도 터미널에서 '
                         '`python3 skills/university-agent/scripts/sync_tls.py --connect`를 먼저 실행해 주세요.') from error
    except (CredentialInputRequired, LoginError, TeacherToolError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
