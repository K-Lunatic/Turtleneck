"""Offline tests for instructor-side Moodle helpers."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.moodle_teaching import (inspect_grading_form, inspect_teacher_capabilities,
                                      observed_submission_files, save_submission_bytes, submission_plan)
from scripts.moodle_teacher import _autonomous_status, _grade_fields, _grading_page


BASE = 'https://moodle.example.edu'


class TeacherPageSession:
    base_url = BASE

    def get_page(self, path):
        if path == '/mod/assign/view.php?id=5':
            return '<a href="/mod/assign/view.php?id=5&action=grading">View all submissions</a>', BASE + path
        if path == BASE + '/mod/assign/view.php?id=5&action=grading':
            return ('''<form action="/mod/assign/view.php?id=5&action=grading">
                       <input name="grade[12]" value="">
                       <a href="/pluginfile.php/12/assignsubmission_file/submission/0/a.pdf">a.pdf</a>
                       </form>''', path)
        raise AssertionError(path)


class AutonomousListSession:
    base_url = 'https://tls.kku.ac.kr'

    def __init__(self, role='운영자'):
        self.role = role

    def get(self, path):
        if path == '/local/ubeclass/my.php':
            return f'''<table><tr><th>번호</th><th>공개</th><th>분류</th><th>강좌</th><th>역할</th><th>상태</th><th>관리</th></tr>
                      <tr><td>1</td><td>비공개</td><td>기타</td>
                      <td><a href="/course/view.php?id=65513">2026년 2학기 자율강좌</a></td>
                      <td>{self.role}</td><td>진행중</td><td><a href="/local/ubeclass/request.php?id=1">수정</a></td></tr></table>'''
        raise AssertionError(path)


class MoodleTeachingTests(unittest.TestCase):
    def test_capabilities_ignore_hidden_management_links(self):
        html = '''
        <a href="/course/modedit.php?update=4">편집</a>
        <div class="accesshide"><a href="/mod/assign/view.php?id=5&action=grading">숨은 채점</a></div>
        <script><a href="/course/modedit.php?add=resource">숨은 추가</a></script>
        '''
        result = inspect_teacher_capabilities(html, BASE)
        self.assertEqual(result['role'], 'teacher_or_manager')
        self.assertTrue(result['capabilities']['courseEditing'])
        self.assertFalse(result['capabilities']['bulkGrading'])
        self.assertNotIn('/mod/assign/view.php', result['evidence'])

    def test_capabilities_require_visible_same_origin_teacher_links(self):
        html = '''
        <a href="/mod/assign/view.php?id=5&action=grading">학생 제출물 채점</a>
        <a href="/course/modedit.php?add=resource">자료 추가</a>
        <a href="https://evil.example/download">외부 링크</a>
        '''
        result = inspect_teacher_capabilities(html, BASE)
        self.assertEqual(result['role'], 'teacher_or_manager')
        self.assertEqual(result['capabilities'], {
            'bulkGrading': True, 'submissionDownload': True,
            'materialUpload': True, 'courseEditing': True,
        })

    def test_submission_files_are_visible_same_origin_links_only(self):
        html = '''
        <a href="/pluginfile.php/12/assignsubmission_file/submission/0/report.pdf">학생 A</a>
        <div class="hidden"><a href="/pluginfile.php/12/assignsubmission_file/submission/0/secret.pdf">숨김</a></div>
        <a href="https://evil.example/file.zip">외부</a>
        <a href="/mod/assign/submission/download.php?id=44">일괄 다운로드</a>
        '''
        files = observed_submission_files(html, BASE)
        self.assertEqual([item['filename'] for item in files], ['report.pdf', 'download.php'])
        self.assertNotIn('secret.pdf', str(files))

    def test_submission_plan_formats_and_rejects_collisions(self):
        files = [{'url': BASE + '/a', 'label': '홍길동', 'filename': 'answer.pdf'},
                 {'url': BASE + '/b', 'label': '김철수', 'filename': 'answer.pdf'}]
        plan = submission_plan(files, course='자료구조', assignment='과제 1',
                               template='{index:02d}_{label}_{filename}')
        self.assertEqual([item['filename'] for item in plan], ['01_홍길동_answer.pdf', '02_김철수_answer.pdf'])
        with self.assertRaises(ValueError):
            submission_plan(files, template='{filename}')
        escaped = submission_plan(files[:1], template='../{filename}')
        self.assertEqual(escaped[0]['filename'], '_answer.pdf')
        self.assertNotIn('..', escaped[0]['filename'])

    def test_save_submission_bytes_is_atomic_and_does_not_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = save_submission_bytes(root, '01_answer.pdf', b'new')
            self.assertEqual(target.read_bytes(), b'new')
            with self.assertRaises(FileExistsError):
                save_submission_bytes(root, '01_answer.pdf', b'old')
            save_submission_bytes(root, '01_answer.pdf', b'replaced', overwrite=True)
            self.assertEqual(target.read_bytes(), b'replaced')
            self.assertEqual(list(root.glob('*.part')), [])

    def test_grading_form_reports_observed_students_without_submitting(self):
        html = '''
        <form action="/course/search.php" method="get"><input name="query" value=""></form>
        <form action="/mod/assign/view.php?id=5&action=grading" method="post">
          <input type="hidden" name="sesskey" value="redacted">
          <input name="grade[12]" value="">
          <input name="grade[13]" value="">
        </form>
        '''
        result = inspect_grading_form(html, BASE)
        self.assertTrue(result['available'])
        self.assertEqual(result['studentCount'], 2)
        self.assertEqual(result['formAction'], '/mod/assign/view.php')

    def test_grade_writer_selects_the_form_that_contains_grade_fields(self):
        html = '''
        <form action="/course/search.php"><input name="query" value=""></form>
        <form action="/mod/assign/view.php?id=5&action=grading">
          <input type="hidden" name="sesskey" value="redacted">
          <input name="grade[12]" value="">
        </form>
        '''
        action, hidden, fields = _grade_fields(html)
        self.assertEqual(action, '/mod/assign/view.php?id=5&action=grading')
        self.assertEqual(hidden['sesskey'], 'redacted')
        self.assertEqual(fields, {'12': ''})

    def test_grading_form_is_strong_evidence_for_bulk_submission_access(self):
        html, page_url, capability = _grading_page(TeacherPageSession(), '5')
        self.assertIn('grade[12]', html)
        self.assertEqual(page_url, BASE + '/mod/assign/view.php?id=5&action=grading')
        self.assertTrue(capability['capabilities']['bulkGrading'])
        self.assertTrue(capability['capabilities']['submissionDownload'])

    def test_autonomous_check_requires_owner_role_and_management_link(self):
        status = _autonomous_status(AutonomousListSession(), 'teacher', '65513')
        self.assertTrue(status['matched'])
        self.assertTrue(status['ownerRoleVisible'])
        self.assertEqual(status['role'], '운영자')

    def test_autonomous_check_accepts_professor_role_and_management_link(self):
        status = _autonomous_status(AutonomousListSession(role='교수'), 'teacher', '65513')
        self.assertTrue(status['ownerRoleVisible'])
        self.assertEqual(status['role'], '교수')


if __name__ == '__main__':
    unittest.main()
