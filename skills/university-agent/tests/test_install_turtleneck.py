import json
import unittest
from unittest.mock import patch

from scripts import install_turtleneck


class InstallTurtleneckTests(unittest.TestCase):
    def test_detect_does_not_install_or_read_secrets(self):
        with patch('scripts.install_turtleneck.shutil.which', side_effect=lambda name: '/usr/bin/' + name):
            state = install_turtleneck.detect()
        self.assertTrue(state['python'])
        self.assertTrue(all(item['installed'] for item in state['agents'].values()))

    def test_check_is_dry_run(self):
        state = {'python': True, 'agents': {'codex': {'installed': True}, 'claude': {'installed': False}, 'gemini': {'installed': False}}}
        with patch('scripts.install_turtleneck.detect', return_value=state), patch('scripts.install_turtleneck.install') as install, patch('builtins.print') as output:
            self.assertEqual(install_turtleneck.main([]), 0)
        install.assert_not_called()
        self.assertEqual(json.loads(output.call_args.args[0])['status'], 'CHECKED')

    def test_apply_runs_install_and_verification_only_for_selected_agent(self):
        with patch('scripts.install_turtleneck.shutil.which', return_value='/usr/bin/codex'), \
             patch('scripts.install_turtleneck._run', return_value=(True, 'listed')) as run, \
             patch('builtins.print') as output:
            self.assertEqual(install_turtleneck.main(['--agent', 'codex', '--apply']), 0)
        self.assertEqual(run.call_count, 3)
        self.assertIn('별 하나', output.call_args_list[-1].args[0])


if __name__ == '__main__':
    unittest.main()
