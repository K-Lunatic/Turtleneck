import shutil
import unittest
from features import gradkuya


@unittest.skipUnless(shutil.which('node'), 'GradKUya needs Node.js 22+')
class GradKUyaTests(unittest.TestCase):
    def transcript(self):
        return {'department': '컴퓨터공학과', 'admissionYear': 2023, 'totalCredits': 0,
                'courses': [{'year': 2023, 'semester': '1학기', 'category': '전필',
                             'code': 'NDGE15060', 'name': '자료구조', 'credits': 3, 'grade': 'F'}]}

    def test_failed_course_remains_required_and_identity_is_not_returned(self):
        transcript = {**self.transcript(), 'studentId': 'fixture-id', 'name': 'fixture-name'}
        result = gradkuya.run({'action': 'audit', 'transcript': transcript})['data']
        self.assertIn('NDGE15060', [row['code'] for row in result['graduation']['remainingRequired']])
        self.assertNotIn('studentId', result['profile'])
        self.assertNotIn('name', result['profile'])

    def test_rejects_missing_admission_handbook_and_duplicate_attempts(self):
        transcript = self.transcript()
        for value in ({**transcript, 'admissionYear': 2022},
                      {**transcript, 'courses': transcript['courses'] * 2}):
            with self.assertRaises(ValueError):
                gradkuya.run({'action': 'audit', 'transcript': value})

    def test_conflicting_fixed_courses_have_no_schedule(self):
        course = {'id': 'a', 'name': 'A', 'group': 'a', 'day': '월', 'start': 9,
                  'end': 11, 'credits': 3, 'fixed': True}
        result = gradkuya.run({'action': 'schedule', 'courses': [course, {**course, 'id': 'b', 'group': 'b'}]})
        self.assertEqual(result['data']['schedules'], [])
        self.assertTrue(result['data']['failure']['conflicts'])


if __name__ == '__main__':
    unittest.main()
