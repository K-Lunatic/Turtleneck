import unittest
from assess import assess


class GateTests(unittest.TestCase):
    def setUp(self):
        self.report = {'representative': [dict(scenario=name, pairs=30, improvement_percent=25,
                       paired_bootstrap_95_percent=[22, 28], learning_records_equal_every_sample=True,
                       python={'http_requests': 9, 'median_seconds': 1},
                       rust={'http_requests': 9, 'median_seconds': .75})
                       for name in ('unchanged_catalog_sync', 'full_metadata_sync')]}
        self.regression = {name: dict(total=1, errors=0, failures=0) for name in ('university', 'server')}
        self.regression['native_calls'] = 1
        self.adapter = dict(python_adapter_tests=6, rust_unit_tests=3, errors=0, failures=0)

    def decision(self):
        return assess(self.report, self.regression, self.adapter)['allow_expansion']

    def test_complete_valid_evidence_allows_next_stage(self):
        self.assertTrue(self.decision())

    def test_micro_speedup_cannot_replace_missing_representative_flow(self):
        self.report['representative'].pop()
        self.assertFalse(self.decision())

    def test_noise_or_insufficient_improvement_stops_expansion(self):
        self.report['representative'][0]['paired_bootstrap_95_percent'][0] = -.1
        self.assertFalse(self.decision())
        self.report['representative'][0]['paired_bootstrap_95_percent'][0] = 1
        self.report['representative'][0]['improvement_percent'] = 19.9
        self.report['representative'][0]['rust']['median_seconds'] = .801
        self.assertFalse(self.decision())
        self.report['representative'][0]['improvement_percent'] = 20.0  # display rounding cannot pass the gate
        self.report['representative'][0]['rust']['median_seconds'] = .8000001
        self.assertFalse(self.decision())

    def test_request_or_data_changes_cannot_be_called_a_speedup(self):
        self.report['representative'][0]['rust']['http_requests'] = 0
        self.assertFalse(self.decision())
        self.report['representative'][0]['rust']['http_requests'] = 9
        self.report['representative'][0]['learning_records_equal_every_sample'] = False
        self.assertFalse(self.decision())

    def test_failed_or_missing_regression_stops_expansion(self):
        del self.regression['server']
        self.assertFalse(self.decision())
        self.regression['server'] = dict(total=1, errors=1, failures=0)
        self.assertFalse(self.decision())


if __name__ == '__main__':
    unittest.main()
