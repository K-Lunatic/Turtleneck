import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from features.document_export import write_document


class DocumentExportTests(unittest.TestCase):
    def test_writes_markdown_and_docx_without_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            markdown = write_document('# 제목\n본문', root / '과제.md')
            docx = write_document('# 제목\n본문', root / '과제.docx')
            self.assertEqual(markdown.read_text(encoding='utf-8'), '# 제목\n본문')
            self.assertTrue(zipfile.is_zipfile(docx))
            with self.assertRaises(ValueError):
                write_document('새 본문', markdown)

    def test_legacy_hwp_is_not_faked(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, '구형 HWP 바이너리'):
                write_document('본문', Path(folder) / '과제.hwp')

    def test_hwpx_reports_missing_converter(self):
        with tempfile.TemporaryDirectory() as folder, patch('features.document_export.shutil.which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'HWPX 쓰기'):
                write_document('본문', Path(folder) / '과제.hwpx')
