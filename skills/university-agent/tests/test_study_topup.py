"""Deficit-only generation preserves compatible candidates and grounded analyses."""
import json
from contextlib import closing
import sqlite3
from unittest.mock import patch
import test_study_pipeline as fixtures


class TopUpTests(fixtures.FilePipelineTests):
    # Only these tests are new; avoid inheriting the fixture's test methods below.
    def request_one(self, count, conversation, kind='mcq', **selection):
        return self.session(conversation).call({'action': 'request', 'selection': {
            'courseId': 'course-1', 'resourceIds': ['r0'], **selection},
            'settings': {'count': count, 'types': [kind] * count}})

    def seed_bank(self, count=4):
        prepared = self.request_one(count, 'seed')
        questions = []
        for i in range(count):
            q = self.candidate(prepared)
            q.update(id=f'q{i}', question=q['question'] + f' 기존 {i}')
            questions.append(q)
        self.extract_questions(self.session('seed'), prepared, questions)

    def submit_new(self, prepared, conversation, kind='mcq'):
        items = []
        for request in prepared['hostOnly']['requests']:
            questions = []
            for i in range(request['settings']['count']):
                q = self.question(kind)
                q.update(id=f'q{i}', question=q['question'] + f' 추가 {request["requestId"]} {i}')
                source = request['SOURCE'][0]
                q['evidence'] = [{'resourceId': source['resourceId'], 'location': source['location'], 'quote': source['text'][:20]}]
                questions.append(q)
            items.append({'requestId': request['requestId'], 'data': {
                'questions': questions, 'types': [{'type': kind, 'reason': '현재 요청 유형'}]}})
        return self.session(conversation).call({'action': 'extract_batch',
            'batchRequestId': prepared['batchRequestId'], 'items': items})

    def test_only_six_added_when_four_become_ten(self):
        self.seed_bank()
        with patch('features.study_materials._read_sections', side_effect=AssertionError('reuse analysis')):
            prepared = self.request_one(10, 'larger')
        self.assertEqual(prepared['hostOnly']['settings']['count'], 6)
        self.assertEqual(len(prepared['hostOnly']['existingQuestions']), 4)
        self.assertNotIn('learning', prepared['hostOnly']['schema'])
        ready = self.submit_new(prepared, 'larger')
        self.assertEqual(ready['totalCandidates'], 10)
        self.assertFalse(ready['hostOnly']['selectionPlan']['missingCount'])
        self.assertIn('기존', self.session('larger').call({'action': 'candidate', 'candidateId': 'c1'})['hostOnly']['question']['question'])
        self.assertTrue(self.request_one(10, 'reused')['needsAssembly'])

    def test_new_type_reuses_facts_but_not_old_questions(self):
        self.seed_bank()
        with patch('features.study_materials._read_sections', side_effect=AssertionError('reuse facts')):
            prepared = self.request_one(3, 'new-type', kind='short')
        self.assertEqual(prepared['hostOnly']['settings']['count'], 3)
        self.assertEqual(prepared['hostOnly']['existingQuestions'], [])
        ready = self.submit_new(prepared, 'new-type', kind='short')
        self.assertEqual(ready['totalCandidates'], 3)
        self.assertTrue(all(q['type'] == 'short' for q in ready['hostOnly']['reviewQuestions']))
        unit = self.session('new-type').call({'action': 'unit', 'unitId': 'u1'})['hostOnly']
        self.assertIn('short', {t['type'] for t in unit['types']})

    def test_bad_result_retry_and_permission_change_preserve_old_bank(self):
        self.seed_bank()
        prepared = self.request_one(10, 'retry')
        with self.assertRaises(ValueError):
            self.session('retry').call({'action': 'extract_batch', 'batchRequestId': prepared['batchRequestId'], 'items': []})
        resumed = self.session('retry').call({'action': 'status'})
        self.assertEqual(resumed['requestId'], prepared['requestId'])
        self.assertEqual(len(resumed['hostOnly']['existingQuestions']), 4)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE resources SET download_status='PROHIBITED' WHERE id='r0'")
        with self.assertRaisesRegex(ValueError, '자료 이용 상태'):
            self.submit_new(prepared, 'retry')
        self.assertEqual(self.request_one(10, 'forbidden')['status'], 'assembling')
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE resources SET download_status='DOWNLOADED' WHERE id='r0'")
        self.assertTrue(self.request_one(4, 'original')['needsAssembly'])

    def test_force_and_changed_source_do_not_reuse(self):
        self.seed_bank()
        self.assertNotIn('reusedAnalysis', self.request_one(10, 'force', rebuildAnalysis=True)['hostOnly'])
        (self.files / '0.txt').write_text('새로운 정렬 자료의 본문입니다.', encoding='utf-8')
        self.assertNotIn('reusedAnalysis', self.request_one(10, 'changed')['hostOnly'])

    def test_legacy_cache_is_not_relabelled_as_new_reference_conditions(self):
        from features import material_cache
        self.seed_bank()
        with closing(sqlite3.connect(self.files.parent / 'study-sessions.db')) as db:
            state = json.loads(db.execute('SELECT state FROM study_sessions WHERE conversation=?', ('seed',)).fetchone()[0])
        cache = self.files.parent / 'cache'
        key = state['pipeline']['analysisKey']
        value = material_cache.get(cache, 'analysis', 'fixture-user', key)
        value.pop('sourceAnalysisKey')
        material_cache.put(cache, 'analysis', 'fixture-user', key, value)
        with closing(sqlite3.connect(cache / 'materials.db')) as db, db:
            db.execute("DELETE FROM material_cache WHERE kind='source-analysis'")
        prepared = self.request_one(10, 'legacy-topup')
        self.submit_new(prepared, 'legacy-topup')
        saved = material_cache.get(cache, 'analysis', 'fixture-user', key)
        self.assertIsNone(saved['sourceAnalysisKey'])
        # Without original reference provenance, a new setting needs one fresh analysis.
        self.assertNotIn('reusedAnalysis', self.request_one(1, 'legacy-new-type', kind='short')['hostOnly'])

    def test_complete_mixed_file_bank_does_not_generate_per_file_type_quotas(self):
        request = {'action': 'request', 'selection': {'courseId': 'course-1', 'allFiles': True},
                   'settings': {'count': 4, 'types': ['mcq', 'short', 'mcq', 'short']}}
        prepared = self.session('mixed-seed').call(request)
        for index in range(4):
            q = self.question('mcq' if index < 2 else 'short')
            q['question'] += str(index)
            source = prepared['hostOnly']['SOURCE'][0]
            q['evidence'] = [{'resourceId': source['resourceId'], 'location': source['location'], 'quote': source['text'][:20]}]
            prepared = self.extract_questions(self.session('mixed-seed'), prepared, [q])
        with patch('features.study_materials._read_sections', side_effect=AssertionError('complete bank')):
            reused = self.session('mixed-reuse').call(request)
        self.assertTrue(reused['needsAssembly'])
        self.assertFalse(reused['hostOnly']['selectionPlan']['missingCount'])
        self.assertEqual(reused['reusedFiles'], 4)


# Reuse setup/helpers without rediscovering the base class's thirty tests.
for _name in fixtures.FilePipelineTests.__dict__:
    if _name.startswith('test_') and _name not in TopUpTests.__dict__:
        setattr(TopUpTests, _name, None)
