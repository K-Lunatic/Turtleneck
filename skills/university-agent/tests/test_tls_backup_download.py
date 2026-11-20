import sys
import unittest
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tls_backup_download import _BackupLinkParser, _CourseContextParser, _looks_like_moodle_backup, _save_backup


class TLSBackupDownloadTests(unittest.TestCase):
    def test_context_id_is_read_from_course_body_class(self):
        parser = _CourseContextParser()
        parser.feed('<body class="two-column context-1465280"><main>course</main></body>')
        self.assertEqual(parser.context_id, "1465280")

    def test_parser_only_returns_visible_matching_course_backup(self):
        parser = _BackupLinkParser("65513")
        parser.feed(
            '<table><tr><td>backup-moodle2-course-65513-demo-20261014-nu.mbz</td>'
            '<td><a href="/pluginfile.php/1/user/backup/demo.mbz?forcedownload=1">다운로드</a></td></tr>'
            '<tr><td>backup-moodle2-course-7-other.mbz</td>'
            '<td><a href="/pluginfile.php/2/user/backup/other.mbz?forcedownload=1">다운로드</a></td></tr></table>'
        )
        self.assertEqual(len(parser.links), 1)
        self.assertEqual(parser.links[0][1], "backup-moodle2-course-65513-demo-20261014-nu.mbz")

    def test_accepts_moodle_archive_signatures(self):
        self.assertTrue(_looks_like_moodle_backup(b"PK\x03\x04..."))
        self.assertTrue(_looks_like_moodle_backup(b"\x1f\x8b\x08..."))
        self.assertTrue(_looks_like_moodle_backup(b".ARCHIVE..."))
        self.assertFalse(_looks_like_moodle_backup(b"<html>"))

    def test_backup_stream_publishes_only_after_signature_check(self):
        class Session:
            base_url = 'https://moodle.example.edu'

            def stream_bytes_to_file(self, url, target, **kwargs):
                self.allowed_origin = kwargs['allowed_origin']
                Path(target).write_bytes(b"PK\x03\x04backup")
                headers = Message(); headers['Content-Type'] = 'application/octet-stream'
                return {'size': 10, 'headers': headers}

        with TemporaryDirectory() as directory:
            target = Path(directory) / 'course.mbz'
            size, content_type = _save_backup(Session(), 'https://tls.kku.ac.kr/backup.mbz', target)
            self.assertEqual((size, content_type), (10, 'application/octet-stream'))
            self.assertEqual(target.read_bytes(), b"PK\x03\x04backup")
            self.assertFalse(target.with_name('.course.mbz.partial').exists())

    def test_backup_stream_uses_session_origin(self):
        class Session:
            base_url = 'https://moodle.example.edu'

            def stream_bytes_to_file(self, url, target, **kwargs):
                self.allowed_origin = kwargs['allowed_origin']
                Path(target).write_bytes(b"PK\x03\x04backup")
                headers = Message(); headers['Content-Type'] = 'application/octet-stream'
                return {'size': 10, 'headers': headers}

        with TemporaryDirectory() as directory:
            session = Session()
            _save_backup(session, 'https://moodle.example.edu/backup.mbz', Path(directory) / 'course.mbz')
            self.assertEqual(session.allowed_origin, 'moodle.example.edu')


if __name__ == "__main__":
    unittest.main()
