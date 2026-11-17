import tempfile
import unittest
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from features.study_sources import save_document, load_document, list_documents, read_document, document_material
from features.study import StudySession
from storage.local_db import LocalDatabase


class SourceLibraryTests(unittest.TestCase):
    def document(self, text='배열은 같은 자료형의 원소를 연속으로 저장한다.'):
        return {'schemaVersion': 1, 'sourceId': 'notion', 'sourceRef': 'selected-page',
                'title': '자료구조 노트', 'sections': [{'location': '블록 1', 'text': text}]}

    def test_reuses_identical_documents_preserves_versions_and_isolates_users(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = save_document(root, 'student', self.document())
            self.assertEqual(save_document(root, 'student', self.document()), first)
            second = save_document(root, 'student', self.document('수정한 원문'))
            self.assertNotEqual(first['documentId'], second['documentId'])
            self.assertEqual(len(list_documents(root, 'student')), 2)
            self.assertEqual(list_documents(root, 'another-student'), [])
            with self.assertRaises(FileNotFoundError):
                load_document(root, 'another-student', first['documentId'])
            material = document_material(root, 'student', first['documentId'])
            self.assertTrue(material['id'].startswith('attachment-'))
            self.assertEqual(material['sections'], first['sections'])

    def test_reads_long_source_without_losing_text_or_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = '가나다라마바사' * 4000
            saved = save_document(root, 'student', self.document(text))
            result, cursor, pieces = None, {'section': 0, 'text_offset': 0}, []
            while cursor:
                result = read_document(root, 'student', saved['documentId'], **cursor)
                self.assertLessEqual(len(result['text']), 12000)
                self.assertEqual(result['location'], '블록 1')
                pieces.append(result['text'])
                cursor = ({'section': result['next']['section'], 'text_offset': result['next']['textOffset']}
                          if result['next'] else None)
            self.assertEqual(''.join(pieces), text)

    def test_rejects_signed_urls_and_unknown_authentication_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ({**self.document(), 'sourceRef': 'https://example.edu/?token=fixture'},
                          {**self.document(), 'cookie': 'fixture'}):
                with self.assertRaises(ValueError):
                    save_document(Path(directory), 'student', value)

    def test_saved_document_enters_existing_concept_and_web_exam_flows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = save_document(root, 'student', self.document())
            provider = Mock()
            provider.get_courses.return_value = []
            provider.get_resources.return_value = []
            for mode in ('concepts', 'quiz'):
                session = StudySession(root / 'study-sessions.db', 'student', mode, provider, root / 'files')
                result = session.call({'action': 'request', 'selection': {'sourceDocumentId': saved['documentId']},
                    'settings': {'mode': mode, 'count': 1, 'delivery': 'web'}})
                self.assertEqual(result['status'], 'prepared')
                if mode == 'quiz':
                    self.assertTrue(result['needsExtraction'])
                else:
                    self.assertTrue(result['needsGeneration'])

    def test_translation_keeps_original_and_requires_its_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = save_document(root, 'student', self.document())
            translated = {**self.document('An array stores elements of the same type contiguously.'),
                'language': 'en', 'translatedFrom': original['documentId']}
            saved = save_document(root, 'student', translated)
            self.assertNotEqual(original['documentId'], saved['documentId'])
            self.assertEqual(load_document(root, 'student', original['documentId']), original)
            translated['sections'] = [{'location': 'invented location', 'text': 'text'}]
            with self.assertRaises(ValueError):
                save_document(root, 'student', translated)

    def test_normal_cli_import_library_read_and_study_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = LocalDatabase(root / 'university.db')
            db.upsert_tls_snapshot('student', [], [], [], 'fixture', None)
            db.close()
            source = root / 'selected.json'
            source.write_text(json.dumps(self.document()), encoding='utf-8')
            runner = Path(__file__).resolve().parents[1] / 'scripts' / 'run_agent.py'
            env = {**os.environ, 'UNIVERSITY_AGENT_DB': str(root / 'university.db'), 'UNIVERSITY_AGENT_USER_ID': 'student'}

            def cli(*args):
                result = subprocess.run([sys.executable, str(runner), *args], capture_output=True,
                    text=True, encoding='utf-8', timeout=10, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            saved = cli('source-document', 'import', '--input', str(source), '--consent')['data']
            library = cli('source-library', '--query', '자료구조')['data']
            self.assertEqual(library['items'][0]['documentId'], saved['documentId'])
            page = cli('source-document', 'read', '--id', saved['documentId'])['data']
            self.assertEqual(page['text'], self.document()['sections'][0]['text'])
            cli('learning-profile', '--updates-json', '{"preferredLanguage":"en"}')
            event = {'action': 'request', 'selection': {'sourceDocumentId': saved['documentId']},
                     'settings': {'mode': 'concepts'}}
            result = cli('study', '--conversation', 'source-cli', '--event-json', json.dumps(event))
            self.assertIn('Output language: en', result['hostOnly']['instruction'])


if __name__ == '__main__':
    unittest.main()
