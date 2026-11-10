"""Privacy-preserving manual-browser traffic comparison checks."""
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('traffic_profile', ROOT / 'experiments/benchmarks/traffic_profile.py')
traffic_profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(traffic_profile)


class TrafficProfileTests(unittest.TestCase):
    def test_har_summary_keeps_sizes_but_not_sensitive_request_data(self):
        summary = traffic_profile.summarize_har({'log': {'startedDateTime': '2026-11-10T04:00:00Z', 'entries': [{
            'request': {'url': 'https://school.invalid/login?token=secret', 'headers': [{'name': 'Cookie', 'value': 'secret'}], 'bodySize': 41},
            'response': {'status': 200, 'bodySize': 100, 'content': {'mimeType': 'text/html'}},
        }]}}, 'academic_sync')
        self.assertEqual(summary['requests'], 1)
        self.assertEqual(summary['bodyBytesLowerBound'], 141)
        self.assertNotIn('secret', str(summary))
        self.assertNotIn('school.invalid', str(summary))

    def test_compare_requires_same_scenario(self):
        skill = {'scenario': 'academic_sync', 'requests': 2, 'responseBodyBytes': 100, 'bodyBytesLowerBound': 100}
        user = {'scenario': 'watch_one_lecture', 'requests': 3, 'responseBodyBytes': 200, 'bodyBytesLowerBound': 200}
        with self.assertRaises(ValueError):
            traffic_profile.compare(skill, user)

    def test_skill_summary_includes_request_bytes_and_boundaries(self):
        metrics = {'requests': 3, 'request_body_bytes': 7, 'response_body_bytes': 100,
                   'statuses': {'200': 1, '302': 1, '503': 1}}
        summary = traffic_profile._skill_metrics(
            {'results': {'tls_sync': {'median': metrics}}}, 'academic_sync')
        self.assertEqual(summary['requestBodyBytes'], 7)
        self.assertEqual(summary['bodyBytesLowerBound'], 107)
        self.assertEqual(summary['redirects'], 1)
        self.assertEqual(summary['failures'], 1)


if __name__ == '__main__':
    unittest.main()
