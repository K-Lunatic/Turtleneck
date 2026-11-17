"""Offline checks for standard Moodle resource links on a non-KKU origin."""
from email.message import Message
from types import SimpleNamespace
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.moodle_provider import MoodleTLSProvider


class StandardResourceSession:
    base_url = 'https://moodle.example.edu'

    def __init__(self):
        self.page_requests = []
        self.byte_requests = []

    def get(self, path):
        self.page_requests.append(path)
        if path == '/my/':
            return '<a href="/course/view.php?id=42">운영체제</a>'
        if path == '/course/view.php?id=42':
            return ('<li class="activity modtype_resource">'
                    '<a href="/mod/resource/view.php?id=7">강의자료</a></li>')
        raise AssertionError(f'unexpected page request: {path}')

    def get_page_info(self, path, **_kwargs):
        self.page_requests.append(path)
        if path == 'https://moodle.example.edu/mod/resource/view.php?id=7':
            headers = Message()
            headers['Content-Type'] = 'text/html'
            return ('<a href="/pluginfile.php/42/mod_resource/content/0/lecture.pdf">'
                    '파일 열기</a>', path, headers)
        raise AssertionError(f'unexpected page info request: {path}')

    def get_bytes(self, path, **_kwargs):
        self.byte_requests.append(path)
        headers = Message()
        headers['Content-Type'] = 'application/pdf'
        headers.add_header('Content-Disposition', 'attachment', filename='lecture.pdf')
        return b'%PDF-standard-moodle', SimpleNamespace(headers=headers, geturl=lambda: path)


class MoodlePortabilityTests(unittest.TestCase):
    def test_standard_resource_view_resolves_same_origin_pluginfile(self):
        session = StandardResourceSession()
        resources = MoodleTLSProvider(session).get_resources('user')
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]['fileName'], 'lecture.pdf')
        self.assertEqual(resources[0]['extension'], 'pdf')
        self.assertEqual(resources[0]['_content'], b'%PDF-standard-moodle')
        self.assertEqual(session.byte_requests, [
            'https://moodle.example.edu/pluginfile.php/42/mod_resource/content/0/lecture.pdf'])

    def test_standard_pluginfile_query_prohibition_stops_before_bytes(self):
        session = StandardResourceSession()
        original = session.get_page_info

        def restricted(path, **kwargs):
            html, page_url, headers = original(path, **kwargs)
            return html.replace('lecture.pdf', 'lecture.pdf?nodownload=1'), page_url, headers

        session.get_page_info = restricted
        resources = MoodleTLSProvider(session).get_resources('user')
        self.assertEqual(resources[0]['downloadStatus'], 'PROHIBITED')
        self.assertEqual(session.byte_requests, [])


if __name__ == '__main__':
    unittest.main()
