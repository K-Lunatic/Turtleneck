import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/everytime/scripts"))

import connect


class EverytimeConnectTests(unittest.TestCase):
    def test_login_page_requires_an_observed_everytime_target(self):
        target = {"url": connect.LOGIN_URL, "webSocketDebuggerUrl": "ws://127.0.0.1:1234/devtools/page/1"}
        with patch.object(connect, "targets", side_effect=[[], [target]]), patch.object(connect.time, "sleep"):
            self.assertEqual(connect.wait_for_login_page(1234, connect.time.monotonic() + 1), target)

    def test_missing_login_page_is_not_reported_as_open(self):
        with patch.object(connect, "targets", return_value=[]):
            with self.assertRaisesRegex(connect.ConnectError, "실제로 표시되지 않았어요"):
                connect.wait_for_login_page(1234, 0)


if __name__ == "__main__":
    unittest.main()
