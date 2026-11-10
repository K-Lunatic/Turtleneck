import unittest

from features.assignment_submission import confirmed, format_submission_result, inspect, safe_url


class AssignmentSubmissionTests(unittest.TestCase):
    HTML = '''
    <form action="/mod/assign/view.php?id=42" method="post">
      <input type="hidden" name="id" value="42">
      <input type="hidden" name="action" value="editsubmission">
      <input type="hidden" name="sesskey" value="private">
      <textarea name="assignsubmission_onlinetext_editor[text]"></textarea>
      <input type="hidden" name="assignsubmission_file_filemanager" value="123">
      <button name="submitbutton" value="저장">저장</button>
    </form>
    <form action="/mod/assign/view.php?id=42" method="post">
      <input type="hidden" name="id" value="42">
      <input type="hidden" name="action" value="submit">
      <input type="hidden" name="sesskey" value="private">
      <button name="submitbutton" value="제출">제출</button>
    </form>
    '''

    def test_inspect_exposes_capabilities_but_not_secret_values(self):
        result = inspect(self.HTML, 'https://tls.example/mod/assign/view.php?id=42&sesskey=private')
        self.assertTrue(result['supportsText'])
        self.assertTrue(result['supportsFileManager'])
        self.assertNotIn('private', str(result))
        self.assertNotIn('sesskey', result['assignmentUrl'])

    def test_confirmation_and_markdown_are_short(self):
        self.assertTrue(confirmed('<p>제출 완료</p>'))
        self.assertFalse(confirmed('<p>아직 제출하지 않음</p>'))
        answer = format_submission_result({'course': '자료구조', 'assignment': 'Ex05',
                                           'status': '제출 완료', 'verified': True,
                                           'files': ['Ex05.java'], 'url': 'https://tls.example/mod/assign/view.php?id=42'})
        self.assertIn('`Ex05.java`', answer)
        self.assertIn('[TLS에서 확인하기]', answer)
        self.assertLess(len(answer), 500)

    def test_safe_url_removes_secret_query_values(self):
        self.assertEqual(safe_url('https://tls.example/x?id=42&sesskey=private'),
                         'https://tls.example/x?id=42')

