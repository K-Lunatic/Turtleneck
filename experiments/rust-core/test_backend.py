import unittest
from unittest.mock import patch
from backend import activate
from providers import moodle_provider
from python_adapter import RustParser


class ActivationTests(unittest.TestCase):
    def test_explicit_modules_restore_even_after_error(self):
        before = (moodle_provider._ActivityParser, moodle_provider._SectionOverviewParser)
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with activate(RustParser()) as enabled:
                self.assertEqual(enabled, ('activity', 'overview'))
                self.assertNotEqual((moodle_provider._ActivityParser, moodle_provider._SectionOverviewParser), before)
                raise RuntimeError('fixture')
        self.assertEqual((moodle_provider._ActivityParser, moodle_provider._SectionOverviewParser), before)

    def test_missing_dll_keeps_python(self):
        before = moodle_provider._ActivityParser
        for error in (OSError('missing'), AttributeError('old ABI')):
            with patch('backend.RustParser', side_effect=error):
                with activate() as enabled:
                    self.assertEqual(enabled, ())
                    self.assertIs(moodle_provider._ActivityParser, before)

    def test_launcher_forwards_arguments_and_enables_only_approved_modules(self):
        import sys
        import run as launcher
        from features import concept_insights
        from python_adapter import ROOT
        activity = moodle_provider._ActivityParser
        rank = concept_insights._rank_bucket
        def called(path, run_name):
            self.assertEqual(path, str(ROOT / 'skills/university-agent/scripts/sync_tls.py'))
            self.assertEqual(sys.argv[1:], ['--ensure', '--metadata-only'])
            self.assertIsNot(moodle_provider._ActivityParser, activity)
            self.assertIs(concept_insights._rank_bucket, rank)
            self.assertEqual(run_name, '__main__')
        with patch.object(sys, 'argv', ['run.py', 'sync_tls', '--ensure', '--metadata-only']), \
             patch.object(launcher.runpy, 'run_path', side_effect=called) as entered:
            launcher.main()
            entered.assert_called_once()
        self.assertIs(moodle_provider._ActivityParser, activity)


if __name__ == '__main__':
    unittest.main()
