import unittest

from features.assignment_draft import format_result, prepare, sources_for_assignment, validate


class AssignmentDraftTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{'sourceId': 'notice-1', 'location': '공지 1', 'sourceKind': 'instructor_notice',
                         'text': '분량은 2쪽이며 표와 참고문헌을 포함하세요.'}]

    def test_prepare_asks_for_unpublished_comment_constraints(self):
        result = prepare(course_name='자료구조', assignment={'title': '보고서', 'dueAt': None}, sources=self.sources)
        self.assertEqual(result['schemaVersion'], 'assignment-draft.v1')
        self.assertIn('교수님이 댓글', result['questionsForUser'][0])
        self.assertNotIn('sesskey', str(result))

    def test_validate_requires_source_evidence_and_blocks_unanswered_requirements(self):
        evidence = [{'sourceId': 'notice-1', 'location': '공지 1', 'quote': '분량은 2쪽이며 표와 참고문헌을 포함하세요.'}]
        pending = validate({'ready': False, 'title': '보고서', 'requirementChecks': [
            {'requirement': '분량 2쪽', 'status': 'confirmed', 'evidence': evidence}],
            'professorChecks': [], 'missingQuestions': ['파일 형식은?'], 'assumptions': []}, self.sources)
        self.assertFalse(pending['ready'])
        self.assertIn('- 확인할 내용: 파일 형식은?', format_result(pending))
        with self.assertRaises(ValueError):
            validate({'ready': True, 'title': '보고서', 'draft': '본문', 'requirementChecks': [
                {'requirement': '분량 2쪽', 'status': 'confirmed', 'evidence': evidence}],
                'professorChecks': [], 'missingQuestions': ['파일 형식은?'], 'assumptions': []}, self.sources)

    def test_ready_result_has_short_markdown_card(self):
        evidence = [{'sourceId': 'notice-1', 'location': '공지 1', 'quote': '분량은 2쪽이며 표와 참고문헌을 포함하세요.'}]
        result = validate({'ready': True, 'title': '보고서', 'format': 'DOCX', 'draft': '본문',
                           'requirementChecks': [{'requirement': '분량 2쪽', 'status': 'confirmed', 'evidence': evidence}],
                           'professorChecks': [{'point': '표와 참고문헌', 'confidence': 'confirmed', 'evidence': evidence}],
                           'missingQuestions': [], 'assumptions': []}, self.sources)
        self.assertIn('✅', format_result(result))
        self.assertIn('교수님 강조', format_result(result))

    def test_sources_include_assignment_detail_and_matching_course_notices_only(self):
        sources = sources_for_assignment(
            {'id': 'tls-assignment-7', 'externalId': '7', 'courseId': 'course-1', 'description': '댓글: 표를 포함하세요.'},
            [{'id': 'n1', 'courseId': 'course-1', 'title': '공지', 'content': '제출 형식은 PDF입니다.'},
             {'id': 'n2', 'courseId': 'course-2', 'title': '다른 과목', 'content': '이 자료는 제외'}],
        )
        self.assertEqual([item['sourceId'] for item in sources], ['assignment-7', 'n1'])
        self.assertIn('제출 형식', sources[1]['text'])

