"""Offline staged extraction, bounded context and persisted resume checks."""
import json
import sqlite3
from contextlib import closing
from unittest.mock import patch
import test_exam_web
from test_project import ProjectTestBase, snapshot, upsert
from storage.local_db import LocalDatabase
from features.study_pipeline import CHUNK_CHARS
from features.study_pipeline import load_chunks, selection_plan, host_response


class FilePipelineTests(ProjectTestBase):
    session = test_exam_web.ExamWebTests.session
    question = staticmethod(test_exam_web.ExamWebTests.question)
    extract_questions = test_exam_web.ExamWebTests.extract_questions

    def setUp(self):
        super().setUp()
        self.files = self.db_path.parent / 'files'
        self.files.mkdir()
        data = snapshot()
        data['resources'] = []
        for index in range(4):
            path = self.files / f'{index}.txt'
            path.write_text('이진 탐색은 정렬된 배열에서 탐색한다.\n', encoding='utf-8')
            data['resources'].append(dict(snapshot()['resources'][0], id=f'r{index}',
                localPath=str(path), fileName=path.name, extension='txt'))
        db = LocalDatabase(self.db_path)
        upsert(db, 'fixture-user', data)
        db.close()

    def request(self):
        return self.session('pipeline').call({'action': 'request',
            'selection': {'courseId': 'course-1', 'allFiles': True},
            'settings': {'count': 4, 'delivery': 'web'}})

    def test_budget_and_focus_are_prepared_once_and_candidate_review_is_batched(self):
        focus = {'concepts': [{'concept': '정렬', 'priority': 80, 'weakness': 50, 'learningMaterial': 'x' * 10000}]}
        with patch('features.study_pipeline.build_insights', return_value=focus) as insights:
            prepared = self.request()
            self.assertEqual(prepared['hostOnly']['settings']['count'], 2)
            self.assertEqual(prepared['hostOnly']['examSettings']['count'], 4)
            self.assertNotIn('learningMaterial', prepared['hostOnly']['learningFocus'][0])
            self.session('pipeline').call({'action': 'status'})
            for index in range(4):
                question = self.candidate(prepared)
                question['question'] += f' ({index + 1})'
                prepared = self.extract_questions(self.session('pipeline'), prepared, [question])
            self.session('pipeline').call({'action': 'catalog'})
            self.assertEqual(insights.call_count, 1)
        plan = prepared['hostOnly']['selectionPlan']
        self.assertEqual(len(plan['candidateIds']), 4)
        self.assertTrue(plan['semanticReviewRequired'])
        result = self.session('pipeline').call({'action': 'candidate', 'candidateIds': plan['candidateIds']})
        self.assertEqual(len(result['hostOnly']['questions']), 4)
        for ids in ([], ['c1'] * 2, ['missing'], ['c1'] * 6):
            with self.assertRaises(ValueError):
                self.session('pipeline').call({'action': 'candidate', 'candidateIds': ids})

    def test_extract_batch_requires_and_stores_every_independent_request(self):
        session = self.session('batch')
        prepared = session.call({'action': 'request',
            'selection': {'courseId': 'course-1', 'allFiles': True},
            'settings': {'count': 4, 'delivery': 'web'}})
        seen = 0
        while prepared.get('needsExtraction'):
            requests = prepared['hostOnly']['requests']
            self.assertLessEqual(len(requests), 2)
            items = []
            for request in requests:
                single = {**prepared, 'hostOnly': request}
                question = self.candidate(single)
                items.append({'requestId': request['requestId'], 'data': {
                    'context': '정렬된 배열에서 이진 탐색하는 수업',
                    'learning': [{'concept': '이진 탐색', 'explanation': '정렬 조건과 범위 축소',
                                  'evidence': question['evidence']}],
                    'types': [{'type': question['type'], 'reason': '탐색 조건 확인'}],
                    'questions': [question], 'shortageReason': '각 부분의 근거 있는 후보만 저장'}})
            with self.assertRaises(ValueError):
                session.call({'action': 'extract_batch',
                              'batchRequestId': prepared['batchRequestId'], 'items': items[:-1]})
            with self.assertRaises(ValueError):
                session.call({'action': 'extract_batch',
                              'batchRequestId': prepared['batchRequestId'], 'items': items + [items[0]]})
            prepared = session.call({'action': 'extract_batch',
                'batchRequestId': prepared['batchRequestId'], 'items': items})
            seen += len(items)
        self.assertEqual(seen, 4)
        self.assertEqual(prepared['totalCandidates'], 4)

    def test_twenty_question_budget_scales_with_files_without_losing_source(self):
        state = {'settings': {'count': 20, 'choices': 4, 'difficulty': '보통', 'types': ['auto'] * 20}, 'selection': {'courseId': 'course-1'},
                 'pipeline': {'files': [f'r{i}' for i in range(7)], 'units': [], 'candidates': []}}
        text = 'x' * (CHUNK_CHARS * 3)
        load_chunks(state, {'id': 'r0', 'title': '자료', 'extension': 'pdf',
                            'contentKey': 'test', 'sections': [{'location': 'p.1', 'text': text}]})
        self.assertEqual(state['pipeline']['candidateTarget'], 2)
        self.assertEqual(''.join(s['text'] for part in state['pipeline']['chunks'] for s in part), text)

    def test_small_cached_bank_does_not_cap_a_larger_exam(self):
        prepared = self.request()
        for i in range(4):
            q = self.candidate(prepared)
            q['question'] += str(i)
            prepared = self.extract_questions(self.session('pipeline'), prepared, [q])
        reused = self.session('same-count').call({'action': 'request',
            'selection': {'courseId': 'course-1', 'allFiles': True}, 'settings': {'count': 4}})
        self.assertTrue(reused['needsAssembly'])
        larger = self.session('larger-count').call({'action': 'request',
            'selection': {'courseId': 'course-1', 'allFiles': True}, 'settings': {'count': 20}})
        self.assertTrue(larger['needsExtraction'])
        self.assertEqual(larger['hostOnly']['settings']['count'], 6)

    def test_thirty_questions_are_not_capped_at_twenty_for_one_part(self):
        prepared = self.session('thirty').call({'action': 'request',
            'selection': {'courseId': 'course-1', 'resourceIds': ['r0']}, 'settings': {'count': 30}})
        self.assertEqual(prepared['hostOnly']['settings']['count'], 36)
        self.assertEqual(prepared['hostOnly']['examSettings']['count'], 30)

    def test_cli_handoff_preserves_requests_without_duplicating_first_source(self):
        prepared = self.request()
        full = json.dumps(prepared, ensure_ascii=False)
        compact = host_response(prepared)
        self.assertEqual(compact['handoffVersion'], 2)
        self.assertEqual(set(compact['hostOnly']), {'requests', 'batchRequestId'})
        self.assertEqual(compact['hostOnly']['requests'], prepared['hostOnly']['requests'])
        self.assertEqual(compact['requestId'], prepared['requestId'])
        self.assertEqual(compact['batchRequestId'], prepared['batchRequestId'])
        self.assertEqual(full, json.dumps(prepared, ensure_ascii=False))
        self.assertEqual(host_response(compact), compact)
        # Direct Python callers keep their legacy first-request view.
        self.assertIn('SOURCE', prepared['hostOnly'])

    def test_compact_handoff_resumes_two_parts_and_accepts_full_batch(self):
        (self.files / '0.txt').write_text('가' * (CHUNK_CHARS + 10), encoding='utf-8')
        session = self.session('handoff-batch')
        prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1',
            'resourceIds': ['r0']}, 'settings': {'count': 2}})
        compact = host_response(prepared)
        self.assertEqual(len(compact['hostOnly']['requests']), 2)
        resumed = host_response(session.call({'action': 'status'}))
        self.assertEqual(compact['hostOnly'], resumed['hostOnly'])
        items = []
        for host in compact['hostOnly']['requests']:
            q = self.candidate({'hostOnly': host})
            q['question'] += host['requestId']
            items.append({'requestId': host['requestId'], 'data': {'context': '본문 확인',
                'learning': [{'concept': '개념', 'explanation': '자료 내용', 'evidence': q['evidence']}],
                'types': [{'type': 'mcq', 'reason': '조건 확인'}], 'questions': [q], 'shortageReason': '근거 있는 후보'}})
        ready = session.call({'action': 'extract_batch', 'batchRequestId': compact['batchRequestId'], 'items': items})
        self.assertEqual(ready['totalCandidates'], 2)
        self.assertTrue(ready['needsAssembly'])
        self.assertIs(host_response(ready), ready)

    def test_python_selection_balances_files_deduplicates_and_reserves_types(self):
        state = {'settings': {'count': 2, 'types': ['auto', 'code_fix']}, 'pipeline': {
            'units': [{'id': 'u1', 'resourceId': 'r1'}, {'id': 'u2', 'resourceId': 'r2'}],
            'candidates': [{'id': 'c1', 'unitId': 'u1', 'type': 'code_fix', 'concept': '코드', 'question': '고치기'},
                           {'id': 'c2', 'unitId': 'u2', 'type': 'mcq', 'concept': '정렬', 'question': '조건'},
                           {'id': 'c3', 'unitId': 'u2', 'type': 'mcq', 'concept': '정렬', 'question': '  조건  '}]}}
        self.assertEqual(selection_plan(state)['candidateIds'], ['c2', 'c1'])
        state['settings'] = {'count': 3, 'types': ['auto'] * 3}
        plan = selection_plan(state)
        self.assertEqual(len(plan['candidateIds']), 2)
        self.assertEqual(plan['missingCount'], 1)
        state['settings'] = {'count': 2, 'types': ['auto'] * 2}
        state['pipeline']['candidates'] = [
            {'id': f'c{i}', 'unitId': 'u1', 'type': 'code_predict', 'concept': '출력',
             'question': '다음 코드의 출력은?', 'code': f'print({i})'} for i in (1, 2)]
        self.assertEqual(selection_plan(state)['candidateIds'], ['c1', 'c2'])

    def candidate(self, prepared):
        q = self.question()
        source = prepared['hostOnly']['SOURCE'][0]
        q['evidence'] = [{'resourceId': source['resourceId'], 'location': source['location'],
                          'quote': source['text'][:30]}]
        return q

    def test_reports_only_guide_assembly_and_changes_reuse_file_analysis(self):
        p = self.request()
        for _ in range(4):
            p = self.extract_questions(self.session('pipeline'), p, [self.candidate(p)])
        for index, text in enumerate(('서술형을 많이 냈어요.', '코드 결과 예측이 많았어요.')):
            ref = {'kind': 'everytime_review', 'courseId': 'course-1', 'professor': '테스트 교수',
                   'semester': '2025-2', 'source': 'https://everytime.kr/lecture/view/1',
                   'location': '후기 7', 'text': text}
            with patch('features.study_materials._read_sections', side_effect=AssertionError('cached sources only')):
                result = self.session(f'reports-{index}').call({'action': 'request',
                    'selection': {'courseId': 'course-1', 'allFiles': True, 'examReferences': [ref]},
                    'settings': {'count': 2}})
            self.assertEqual(result['reusedFiles'], 4)
            self.assertEqual(result['hostOnly']['examReferences'][0]['text'], text)
            self.assertNotIn('SOURCE', result['hostOnly'])

    def test_transcript_is_chunked_as_source_and_reference_use_is_preserved(self):
        ref = {'kind': 'instructor_transcript', 'courseId': 'course-1', 'source': '교수 강의 녹음 전사문',
               'location': '00:12:00~00:18:00', 'text': '정렬된 배열을 강조합니다. ' * 2000}
        session = self.session('transcript')
        p = session.call({'action': 'request', 'selection': {'courseId': 'course-1',
            'resourceIds': ['r0'], 'examReferences': [ref]}, 'settings': {'count': 3}})
        self.assertEqual(p['progress']['totalFiles'], 2)
        p = self.extract_questions(session, p, [self.candidate(p)])
        while p.get('needsExtraction'):
            source = p['hostOnly']['SOURCE'][0]
            self.assertTrue(source['resourceId'].startswith('attachment-'))
            self.assertEqual(source['location'], ref['location'])
            self.assertLessEqual(sum(len(s['text']) for s in p['hostOnly']['SOURCE']), CHUNK_CHARS)
            p = self.extract_questions(self.session('transcript'), p, [self.candidate(p)])
        reference = p['hostOnly']['examReferences'][0]
        self.assertNotIn('text', reference)
        choices = [q['id'] for q in p['hostOnly']['candidates']]
        with self.assertRaises(ValueError):
            session.call({'action': 'assemble', 'candidateIds': choices, 'referenceUse': [
                {'referenceId': 'unknown', 'candidateIds': choices, 'reason': '알 수 없는 출처'}]})
        result = session.call({'action': 'assemble', 'candidateIds': choices, 'referenceUse': [
            {'referenceId': reference['id'], 'candidateIds': choices[1:], 'reason': '교수가 강조한 정렬 조건을 더 연습하도록 선택'}]})
        self.assertEqual(result['referenceUse'][0]['questionIds'], ['q2', 'q3'])
        with closing(sqlite3.connect(session.path)) as db, db:
            state = json.loads(db.execute('SELECT state FROM study_sessions WHERE conversation=?', ('transcript',)).fetchone()[0])
            self.assertNotIn('examReferences', state['selection'])
            self.assertLess(len(json.dumps(state)), 50000)
            self.assertNotIn('text', state['examReferences'][0])
        session.call({'action': 'cancel'})
        with closing(sqlite3.connect(session.path)) as db, db:
            saved = json.loads(db.execute('SELECT state FROM study_exams WHERE exam_id=?', (result['examId'],)).fetchone()[0])
            self.assertEqual(saved['referenceUse'], result['referenceUse'])

    def test_transcript_only_supported_but_reports_cannot_replace_sources(self):
        ref = {'kind': 'instructor_transcript', 'courseId': 'course-1', 'source': '교수 필사본',
               'location': '필사 줄 1', 'text': '이진 탐색은 정렬된 배열에서 탐색한다.'}
        p = self.session('transcript-only').call({'action': 'request', 'selection': {
            'courseId': 'course-1', 'resourceIds': [], 'examReferences': [ref, dict(ref)]}, 'settings': {'count': 1}})
        self.assertEqual(p['progress']['totalFiles'], 1)
        self.assertEqual(p['hostOnly']['SOURCE'][0]['text'], ref['text'])
        self.assertEqual(p['hostOnly']['sourceKind'], 'instructor_transcript')
        question = self.candidate(p)
        self.assertEqual(self.extract_questions(self.session('transcript-only'), p, [question])['totalCandidates'], 1)
        with patch('features.study_pipeline.load_chunks', side_effect=AssertionError('reuse transcript analysis')):
            reused = self.session('same-transcript').call({'action': 'request', 'selection': {
                'courseId': 'course-1', 'resourceIds': [], 'examReferences': [dict(ref)]}, 'settings': {'count': 1}})
        self.assertEqual(reused['reusedFiles'], 1)
        changed = self.session('changed-transcript').call({'action': 'request', 'selection': {
            'courseId': 'course-1', 'resourceIds': [], 'examReferences': [{**ref, 'text': '새로 확인한 교수 강조 내용'}]}, 'settings': {'count': 1}})
        self.assertEqual(changed['hostOnly']['SOURCE'][0]['text'], '새로 확인한 교수 강조 내용')
        with self.assertRaises(ValueError):
            self.session('reports-only').call({'action': 'request', 'selection': {
                'courseId': 'course-1', 'resourceIds': [], 'examReferences': [{**ref, 'kind': 'student_report'}]}})

    def test_reference_scope_types_and_testimony_cannot_supply_an_answer(self):
        from features.study import exam_references
        course = {'id': 'course-1', 'professor': '김교수'}
        ref = {'kind': 'student_report', 'courseId': 'course-1', 'professor': '김교수',
               'source': '사용자의 수강 경험', 'location': '이 대화', 'text': '서술형 위주였어요.'}
        self.assertEqual(exam_references([], course), [])
        for changed in ({'courseId': 'other'}, {'professor': '다른 교수'}, {'kind': 'paper'},
                        {'text': 'x' * 2001}, {'source': ''}, {'password': 'never-accepted'}):
            with self.assertRaises(ValueError):
                exam_references([{**ref, **changed}], course)
        session = self.session('unsupported-quote')
        prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1',
            'resourceIds': ['r0'], 'examReferences': [ref]}, 'settings': {'count': 1}})
        question = self.candidate(prepared)
        question['evidence'] = [{'resourceId': exam_references([ref], course)[0]['id'],
                                'location': ref['location'], 'quote': ref['text']}]
        with self.assertRaises(ValueError):
            self.extract_questions(session, prepared, [question])
        self.assertEqual(self.session('unsupported-quote').call({'action': 'status'})['requestId'], prepared['requestId'])

    def test_source_assessments_are_validated_and_saved_separately(self):
        from features.study import exam_references
        review = {'kind': 'everytime_review', 'courseId': 'course-1', 'professor': '테스트 교수',
                  'semester': '2025-2', 'source': 'https://everytime.kr/lecture/view/1',
                  'location': '후기 1', 'text': '정렬이 반복되어 나왔어요.'}
        session = self.session('source-assessments')
        prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1', 'resourceIds': ['r0'],
            'examReferences': [review]}, 'settings': {'count': 1}})
        question = self.candidate(prepared)
        refs = question['evidence']
        ref_id = exam_references([review], {'id': 'course-1', 'professor': '테스트 교수'})[0]['id']
        response = {'context': '정렬된 배열에서 이진 탐색하는 수업',
                    'learning': [{'concept': '이진 탐색', 'explanation': '정렬 조건', 'evidence': refs,
                                  'importanceBySource': [{'sourceKind': 'everytime_review', 'score': 70,
                                                          'reason': '후기에서 반복 언급', 'referenceIds': [ref_id]}]}],
                    'types': [{'type': question['type'], 'reason': '조건 확인'}], 'questions': [question],
                    'shortageReason': '현재 부분의 근거 있는 후보만 저장'}
        result = session.call({'action': 'extract', 'requestId': prepared['requestId'], 'data': response})
        unit = session.call({'action': 'unit', 'unitId': 'u1'})['hostOnly']
        self.assertEqual(unit['learning'][0]['importanceBySource'][0]['sourceKind'], 'everytime_review')
        with self.assertRaises(ValueError):
            session.call({'action': 'extract', 'requestId': result.get('requestId'), 'data': {}})

    def test_all_files_must_finish_resume_and_private_question_bank(self):
        prepared = self.request()
        for index in range(4):
            session = self.session('pipeline')
            with self.assertRaises(ValueError):
                session.call({'action': 'assemble', 'candidateIds': []})
            with self.assertRaises(ValueError):
                session.call({'action': 'generate', 'requestId': prepared['requestId'], 'data': {'questions': []}})
            self.assertEqual(prepared['progress']['processedFiles'], index)
            original = prepared['requestId']
            q = self.candidate(prepared)
            prepared = self.extract_questions(session, prepared, [q])
            with self.assertRaises(ValueError):
                session.call({'action': 'extract', 'requestId': original, 'data': {}})
            prepared = self.session('pipeline').call({'action': 'status'})
        self.assertEqual(prepared['totalCandidates'], 4)
        page = session.call({'action': 'catalog', 'limit': 1})
        self.assertEqual(len(page['hostOnly']['candidates']), 1)
        self.assertEqual(page['nextOffset'], 1)
        unit = session.call({'action': 'unit', 'unitId': 'u1'})['hostOnly']
        self.assertEqual(unit['context'], '정렬된 배열에서 이진 탐색하는 수업')
        self.assertEqual(unit['types'][0]['type'], 'mcq')
        session.call({'action': 'assemble', 'candidateIds': ['c1', 'c2', 'c3', 'c4']})
        public = session.call({'action': 'web_status'})
        session.call({'action': 'start_exam', 'examId': public['examId']})
        public = session.call({'action': 'web_status'})
        self.assertEqual(len(public['questions']), 4)
        self.assertNotIn('rubric', json.dumps(public))
        with closing(sqlite3.connect(self.db_path.parent / 'study-sessions.db')) as db, db:
            saved = json.loads(db.execute('SELECT state FROM study_sessions').fetchone()[0])
            pipeline = json.loads(db.execute('SELECT state FROM study_pipelines WHERE user=? AND exam_id=?',
                ('fixture-user', saved['analysisRef'])).fetchone()[0])
        self.assertNotIn('pipeline', saved)
        self.assertEqual(len(pipeline['units']), 4)

    def test_catalog_reads_do_not_rewrite_large_session(self):
        prepared = self.request()
        for _ in range(4):
            prepared = self.extract_questions(self.session('pipeline'), prepared, [self.candidate(prepared)])
        path = self.db_path.parent / 'study-sessions.db'
        with closing(sqlite3.connect(path)) as observer, observer:
            before = observer.execute('PRAGMA data_version').fetchone()[0]
            original = observer.execute('SELECT state FROM study_sessions').fetchone()[0]
            self.session('pipeline').call({'action': 'catalog'})
            self.session('pipeline').call({'action': 'unit', 'unitId': 'u1'})
            self.session('pipeline').call({'action': 'candidate', 'candidateId': 'c1'})
            self.assertEqual(observer.execute('PRAGMA data_version').fetchone()[0], before)
            self.assertEqual(observer.execute('SELECT state FROM study_sessions').fetchone()[0], original)

    def test_completed_files_reused_across_chats_and_changed_or_forbidden_files_not_reused(self):
        prepared = self.request()
        for _ in range(4):
            prepared = self.extract_questions(self.session('pipeline'), prepared, [self.candidate(prepared)])
        request = {'action': 'request', 'selection': {'courseId': 'course-1', 'allFiles': True},
                   'settings': {'count': 2, 'delivery': 'web'}}
        with patch('features.study_materials._read_sections', side_effect=AssertionError('must reuse analysis')), \
             patch('features.study_pipeline.load_chunks', side_effect=AssertionError('must not split again')), \
             patch('pathlib.Path.open', side_effect=AssertionError('must not read unchanged originals')):
            reused = self.session('second').call(request)
        self.assertEqual(reused['reusedFiles'], 4)
        self.assertEqual(reused['totalCandidates'], 4)
        from features import analysis_records
        db = LocalDatabase(self.db_path)
        try:
            records = analysis_records.read(self.files.parent, 'fixture-user', db.get_resources('fixture-user'))
        finally:
            db.close()
        self.assertEqual(len(records['records']), 4)  # Reuse does not invent new analysis revisions.
        self.assertEqual({r['resourceId'] for r in records['records']}, {'r0', 'r1', 'r2', 'r3'})
        invalid_range = self.session('empty-range').call({**request,
            'selection': {'courseId': 'course-1', 'resourceIds': ['r0'], 'locations': {'r0': []}}})
        self.assertEqual(len(invalid_range['failures']), 1)
        self.assertEqual(invalid_range['reusedFiles'], 0)
        (self.files / '0.txt').write_text('자료를 새 내용으로 수정했습니다.\n', encoding='utf-8')
        changed = self.session('third').call(request)
        self.assertTrue(changed['needsExtraction'])
        self.assertIn('새 내용', changed['hostOnly']['SOURCE'][0]['text'])
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE resources SET download_status='PROHIBITED', download_reason='다운로드 금지' WHERE id='r0'")
        forbidden = self.session('fourth').call(request)
        self.assertEqual(forbidden['reusedFiles'], 3)
        self.assertEqual(len(forbidden['failures']), 1)

    def test_chunk_boundaries_preserved_without_suffix_copy(self):
        from features.study_pipeline import load_chunks
        text = '가나다' * 10000
        state = {'pipeline': {'units': [], 'candidates': []}, 'settings': {'choices': 4, 'difficulty': '보통', 'types': ['auto']},
                 'selection': {'courseId': 'c'}}
        load_chunks(state, {'id': 'r', 'title': '자료', 'sections': [{'location': '1', 'text': text}, {'location': '2', 'text': '끝'}]})
        chunks = state['pipeline']['chunks']
        self.assertEqual(''.join(s['text'] for part in chunks for s in part), text + '끝')
        self.assertTrue(all(sum(len(s['text']) for s in part) <= CHUNK_CHARS for part in chunks))
        self.assertEqual(chunks[-1][-1]['location'], '2')

    def test_review_questions_are_private_and_follow_selected_order(self):
        prepared = self.request()
        for i in range(4):
            q = self.candidate(prepared)
            q['question'] += str(i)
            prepared = self.extract_questions(self.session('pipeline'), prepared, [q])
        host = prepared['hostOnly']
        self.assertEqual([q['id'] for q in host['reviewQuestions']], host['selectionPlan']['candidateIds'])
        self.assertFalse(host['reviewRemainingIds'])
        self.assertIn('answer', host['reviewQuestions'][0])
        self.assertNotIn('reviewQuestions', {k: v for k, v in prepared.items() if k != 'hostOnly'})

    def test_review_payload_is_bounded_and_remaining_ids_are_returned(self):
        from features.study_pipeline import catalog
        question = {**self.question(), 'id': 'c1', 'unitId': 'u1', 'explanation': 'x' * 60001}
        state = {'settings': {'count': 1, 'types': ['auto']}, 'pipeline': {
            'files': ['r0'], 'fileIndex': 1, 'failures': [], 'learningFocus': [],
            'units': [{'id': 'u1', 'resourceId': 'r0'}], 'candidates': [question]}}
        host = catalog(self.session('bounded'), state, {})['hostOnly']
        self.assertEqual(host['reviewQuestions'], [])
        self.assertEqual(host['reviewRemainingIds'], ['c1'])

    def test_generation_metrics_survive_resume_and_are_saved_at_assembly(self):
        session = self.session('timed')
        with patch('features.study_pipeline.time.time', return_value=100):
            prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1',
                'resourceIds': ['r0']}, 'settings': {'count': 1}})
        with patch('features.study_pipeline.time.time', return_value=110):
            session.call({'action': 'status'})
        with patch('features.study_pipeline.time.time', return_value=130):
            ready = self.extract_questions(session, prepared, [self.candidate(prepared)])
        self.assertEqual(ready['generationMetrics']['hostHandoffSeconds'], 30)
        with patch('features.study_pipeline.time.time', return_value=140):
            result = session.call({'action': 'assemble', 'candidateIds': ['c1']})
        self.assertEqual(result['generationMetrics'], {'requestToAssemblySeconds': 40,
            'hostHandoffSeconds': 30, 'completedBatches': 1})
        with closing(sqlite3.connect(session.path)) as db:
            saved = json.loads(db.execute('SELECT state FROM study_sessions WHERE conversation=?', ('timed',)).fetchone()[0])
        self.assertEqual(saved['generationMetrics'], result['generationMetrics'])

    def test_previous_8000_character_analysis_is_reused(self):
        from features.study_pipeline import analysis_key
        from features.study_materials import study_materials
        from features import material_cache
        prepared = self.request()
        for i in range(4):
            prepared = self.extract_questions(self.session('pipeline'), prepared, [self.candidate(prepared)])
        session = self.session('pipeline')
        with closing(sqlite3.connect(session.path)) as db:
            state = json.loads(db.execute('SELECT state FROM study_sessions').fetchone()[0])
        cache = self.files.parent / 'cache'
        for rid in ('r0', 'r1', 'r2', 'r3'):
            material = study_materials(session.provider.get_courses('fixture-user'), session.provider.get_resources('fixture-user'),
                files_root=self.files, course_id='course-1', resource_ids=[rid], include_ids=True, metadata_only=True)['data']['materials'][0]
            current, old = analysis_key(state, material), analysis_key(state, material, chunk_chars=8000)
            value = material_cache.get(cache, 'analysis', 'fixture-user', current)
            material_cache.put(cache, 'analysis', 'fixture-user', old, value)
            with closing(sqlite3.connect(cache / 'materials.db')) as db, db:
                db.execute('DELETE FROM material_cache WHERE kind=? AND key=?', ('analysis', current))
        with patch('features.study_materials._read_sections', side_effect=AssertionError('reuse old analysis')):
            reused = self.session('old-cache').call({'action': 'request', 'selection': {'courseId': 'course-1',
                'allFiles': True}, 'settings': {'count': 4}})
        self.assertTrue(reused['needsAssembly'])
        self.assertEqual(reused['reusedFiles'], 4)

    def test_batch_checks_changed_source_permission(self):
        prepared = self.request()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE resources SET download_status='PROHIBITED' WHERE id='r0'")
        with self.assertRaisesRegex(ValueError, '자료 이용 상태'):
            self.session('pipeline').call({'action': 'extract_batch',
                'batchRequestId': prepared['batchRequestId'], 'items': []})

    def test_compact_extraction_matches_full_validated_questions(self):
        request = {'action': 'request', 'selection': {'courseId': 'course-1', 'resourceIds': ['r0']},
                   'settings': {'count': 1, 'types': ['mcq']}}
        full, compact = self.session('full-payload'), self.session('compact-payload')
        first, second = full.call(request), compact.call(request)
        schema = first['hostOnly']['schema']
        self.assertIn('answerIndex', schema['questions'][0])
        self.assertNotIn('blocks', schema['questions'][0])
        self.assertEqual(schema['questionDefaults']['type'], 'mcq')
        q = self.candidate(first)
        self.extract_questions(full, first, [q])
        defaults = {key: q[key] for key in ('type', 'concept', 'hint', 'rubric')}
        short = {key: value for key, value in q.items() if key not in {*defaults, 'answer', 'id', 'evidence'}}
        short.update(answerIndex=q['options'].index(q['answer']),
                     evidence=[{'sourceIndex': 0, 'quote': q['evidence'][0]['quote']}])
        compact.call({'action': 'extract', 'requestId': second['requestId'], 'data': {
            'context': '정렬된 배열에서 이진 탐색하는 수업', 'questionDefaults': defaults,
            'learning': [{'concept': '이진 탐색', 'explanation': '정렬 조건과 범위 축소', 'evidence': short['evidence']}],
            'types': [{'type': 'mcq', 'reason': '탐색 조건을 확인한다'}], 'questions': [short], 'shortageReason': '근거 있는 후보'}})
        self.assertEqual(full.call({'action': 'candidate', 'candidateId': 'c1'})['hostOnly'],
                         compact.call({'action': 'candidate', 'candidateId': 'c1'})['hostOnly'])

    def test_compact_indices_and_defaults_cannot_bypass_validation(self):
        from features.study_pipeline import _expand_questions, _expand_evidence
        sources = [{'resourceId': 'r0', 'location': '1', 'text': '정렬'}]
        for index in (-1, 1, True, '0'):
            with self.subTest(sourceIndex=index), self.assertRaises(ValueError):
                _expand_evidence([{'sourceIndex': index, 'quote': '정렬'}], sources)
            with self.subTest(answerIndex=index), self.assertRaises(ValueError):
                _expand_questions({'questions': [{'options': ['정렬'], 'answerIndex': index}]}, sources)
        for data in ({'questionDefaults': {'answer': '정렬'}},
                     {'questions': [{'options': ['정렬'], 'answerIndex': 0, 'answer': '다름'}]}):
            with self.assertRaises(ValueError):
                _expand_questions(data, sources)
        with self.assertRaises(ValueError):
            _expand_evidence([{'sourceIndex': 0, 'quote': '정렬', 'resourceId': '다른 자료'}], sources)

    def test_compact_evidence_still_rejects_invented_quotes(self):
        session = self.session('compact-provenance')
        prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1',
            'resourceIds': ['r0']}, 'settings': {'count': 1}})
        q = self.candidate(prepared)
        q['evidence'] = [{'sourceIndex': 0, 'quote': '자료에 존재하지 않는 원문'}]
        with self.assertRaises(ValueError):
            self.extract_questions(session, prepared, [q])
        self.assertEqual(session.call({'action': 'status'})['requestId'], prepared['requestId'])

    def test_legacy_text_analysis_is_invalidated_after_decoder_change(self):
        from features import material_cache
        from features.study_materials import study_materials
        p = self.request()
        for _ in range(4):
            p = self.extract_questions(self.session('pipeline'), p, [self.candidate(p)])
        session = self.session('pipeline')
        with closing(sqlite3.connect(self.files.parent / 'study-sessions.db')) as db, db:
            state = json.loads(db.execute('SELECT state FROM study_sessions').fetchone()[0])
        material = study_materials(session.provider.get_courses('fixture-user'), session.provider.get_resources('fixture-user'),
            files_root=self.files, course_id='course-1', resource_ids=['r3'], include_ids=True, max_chars=10000000)['data']['materials'][0]
        config = {k: state['settings'][k] for k in ('choices', 'difficulty')}
        config['types'] = sorted(set(state['settings']['types']))
        old_key = material_cache.key(['analysis-v1', CHUNK_CHARS, 'course-1',
            {k: v for k, v in material.items() if k != 'contentKey'}, config])
        root = self.files.parent / 'cache'
        value = material_cache.get(root, 'analysis', 'fixture-user', state['pipeline']['analysisKey'])
        material_cache.put(root, 'analysis', 'fixture-user', old_key, value)
        with closing(sqlite3.connect(root / 'materials.db')) as db, db:
            db.execute('DELETE FROM material_cache WHERE kind=? AND key=?', ('analysis', state['pipeline']['analysisKey']))
        reused = self.session('upgrade').call({'action': 'request', 'selection': {'courseId': 'course-1', 'allFiles': True},
            'settings': {'count': 4, 'delivery': 'web'}})
        self.assertTrue(reused['needsExtraction'])
        self.assertEqual(reused['progress']['processedFiles'], 3)

    def test_failed_cache_save_retry_does_not_duplicate_analysis(self):
        from features import analysis_records
        session = self.session('retry')
        prepared = session.call({'action': 'request', 'selection': {'courseId': 'course-1', 'resourceIds': ['r0']}, 'settings': {'count': 1}})
        question = self.candidate(prepared)
        with patch('features.material_cache.put', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):
                self.extract_questions(session, prepared, [question])
        self.extract_questions(session, prepared, [question])
        records = analysis_records.read(self.files.parent, 'fixture-user', session.provider.get_resources('fixture-user'))
        self.assertEqual(len(records['records']), 1)

    def test_old_completed_pipeline_migrates_once_and_draft_is_small(self):
        p = self.request()
        for _ in range(4):
            p = self.extract_questions(self.session('pipeline'), p, [self.candidate(p)])
        session = self.session('pipeline')
        session.call({'action': 'assemble', 'candidateIds': ['c1', 'c2', 'c3', 'c4']})
        path = self.files.parent / 'study-sessions.db'
        with closing(sqlite3.connect(path)) as db, db:
            state = json.loads(db.execute('SELECT state FROM study_sessions').fetchone()[0])
            old = json.loads(db.execute('SELECT state FROM study_pipelines').fetchone()[0])
            old['largeOriginal'] = 'x' * 1000000
            state['pipeline'] = old
            db.execute('UPDATE study_sessions SET state=?', (json.dumps(state),))
        session.call({'action': 'start_exam', 'examId': state['examId']})
        session.call({'action': 'draft', 'examId': state['examId'], 'revision': 0, 'answers': {}})
        with closing(sqlite3.connect(path)) as db, db:
            small = db.execute('SELECT state FROM study_sessions').fetchone()[0]
            preserved = db.execute('SELECT state FROM study_pipelines').fetchone()[0]
            self.assertLess(len(small), 50000)
            self.assertIn('largeOriginal', preserved)
            version = db.execute('PRAGMA data_version').fetchone()[0]
            session.call({'action': 'web_status'})
            self.assertEqual(db.execute('PRAGMA data_version').fetchone()[0], version)
            session.call({'action': 'draft', 'examId': state['examId'], 'revision': 1, 'answers': {'q1': '1'}})
            self.assertEqual(db.execute('SELECT state FROM study_pipelines').fetchone()[0], preserved)

    def test_long_file_chunk_bound_and_bad_evidence_does_not_advance(self):
        (self.files / '0.txt').write_text('정렬 조건 ' * 4000, encoding='utf-8')
        p = self.request()
        self.assertGreater(p['progress']['totalParts'], 1)
        total = p['progress']['totalParts']
        for part in range(total):
            self.assertLessEqual(sum(len(s['text']) for s in p['hostOnly']['SOURCE']), CHUNK_CHARS)
            q = self.candidate(p)
            q['evidence'][0]['quote'] = '원문에 없는 인용'
            with self.assertRaises(ValueError):
                self.extract_questions(self.session('pipeline'), p, [q])
            resumed = self.session('pipeline').call({'action': 'status'})
            self.assertEqual(resumed['requestId'], p['requestId'])
            p = self.extract_questions(self.session('pipeline'), p, [self.candidate(p)])
        self.assertEqual(p['progress']['processedFiles'], 1)

    def test_prohibited_file_never_opened_and_exclusion_requires_consent(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE resources SET download_status='PROHIBITED', download_reason='다운로드 금지' WHERE id='r0'")
        with patch('features.study_materials.Path.read_text', side_effect=AssertionError('must not read forbidden file')):
            # Metadata restriction is checked before the text reader is called.
            from features.study_materials import study_materials
            db = LocalDatabase(self.db_path, read_only=True)
            try:
                result = study_materials(db.get_courses('fixture-user'), db.get_resources('fixture-user'),
                    files_root=self.files, course_id='course-1', resource_ids=['r0'])
                self.assertIn('금지', result['data']['materials'][0]['error'])
            finally:
                db.close()
        p = self.request()
        self.assertEqual(len(p['failures']), 1)
        for _ in range(3):
            p = self.extract_questions(self.session('pipeline'), p, [self.candidate(p)])
        with self.assertRaisesRegex(ValueError, '동의'):
            self.session('pipeline').call({'action': 'assemble', 'candidateIds': ['c1']})
        self.session('pipeline').call({'action': 'assemble', 'candidateIds': ['c1'],
            'acceptExclusions': True, 'shortageReason': '다운로드 금지 자료 제외'})
