import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from features import presentation


class PresentationTests(unittest.TestCase):
    def test_browser_is_used_when_companion_is_absent(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(presentation, 'RUNTIME_PATH', Path(directory) / 'absent.json'), \
             patch.object(presentation.webbrowser, 'open', return_value=True) as browser:
            result = presentation.open_local_page('http://127.0.0.1:1234/#test')
        self.assertEqual(result, {'target': 'browser', 'requested': True})
        browser.assert_called_once()

    def test_running_companion_receives_page_and_browser_falls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'runtime.json'
            marker.write_text(json.dumps({'port': 1234, 'token': 'x' * 40}))
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"accepted":true}'
            opener = MagicMock()
            opener.open.return_value = response
            with patch.object(presentation, 'RUNTIME_PATH', marker), \
                 patch.object(presentation, 'build_opener', return_value=opener), \
                 patch.object(presentation.webbrowser, 'open', return_value=True) as browser:
                self.assertEqual(presentation.open_local_page('http://127.0.0.1:7777/', kind='login')['target'], 'companion')
                browser.assert_not_called()
                opener.open.side_effect = OSError('companion exited')
                self.assertEqual(presentation.open_local_page('http://127.0.0.1:7777/')['target'], 'browser')
                browser.assert_called_once()

    def test_rejects_remote_urls_before_display(self):
        with patch.object(presentation.webbrowser, 'open') as browser:
            with self.assertRaises(ValueError):
                presentation.open_local_page('https://school.example/')
            browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()
