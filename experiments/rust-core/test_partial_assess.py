import unittest
from assess_partial import assess


class PartialGateTests(unittest.TestCase):
    def setUp(self):
        def row(name, rust=.7):
            return dict(scenario=name, python={'median_seconds': 1}, rust={'median_seconds': rust},
                        outputs_equal=True, pairs=30, paired_bootstrap_95_percent=[20, 40])
        self.report = {group: [row(group + '_100'), row(group + '_1000')]
                       for group in ('activity', 'overview', 'concept_rank', 'concept_flow')}
        self.report['representative'] = [row('unchanged_catalog_sync', .99), row('full_metadata_sync', 1)]
        for item in self.report['representative']:
            item['paired_bootstrap_95_percent'] = [-1, 2]
        self.tests = {name: dict(total=1, errors=0, failures=0) for name in ('university', 'server')}
        self.experiments = dict(rust_unit_tests=6, python_experiment_tests=27, errors=0, failures=0)

    def assess(self):
        return assess(self.report, self.tests, self.experiments)

    def test_partial_gain_is_allowed_without_twenty_percent_overall_gain(self):
        self.tests['html_calls_by_kind'] = {'activity': 10, 'overview': 10}
        result = self.assess()
        self.assertTrue(result['modules']['overview']['adopt'])
        self.assertFalse(result['full_rewrite_authorized'])

    def test_slow_concept_path_does_not_block_good_html_modules(self):
        self.report['concept_flow'][0]['rust']['median_seconds'] = 1.3
        result = self.assess()
        self.assertFalse(result['modules']['concept']['adopt'])
        self.assertTrue(result['modules']['activity']['adopt'])

    def test_applicable_flow_regression_blocks_its_html_adoption(self):
        self.report['representative'][0]['paired_bootstrap_95_percent'] = [-10, 0]
        result = self.assess()
        self.assertFalse(result['modules']['overview']['adopt'])

    def test_failed_regression_and_changed_outputs_never_adopt(self):
        self.report['overview'][0]['outputs_equal'] = False
        self.assertFalse(self.assess()['modules']['overview']['adopt'])
        self.tests['server']['errors'] = 1
        self.assertFalse(self.assess()['modules']['activity']['adopt'])
        self.tests['server']['errors'] = 0
        self.experiments['failures'] = 1
        self.assertFalse(self.assess()['modules']['activity']['adopt'])

    def test_missing_measurements_never_adopt(self):
        self.report['activity'] = []
        self.assertFalse(self.assess()['modules']['activity']['adopt'])
        self.report['representative'] = []
        self.assertFalse(self.assess()['modules']['overview']['adopt'])


if __name__ == '__main__':
    unittest.main()
