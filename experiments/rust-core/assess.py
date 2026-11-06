"""Fail closed on missing/failed validation before another migration stage."""
import json
from pathlib import Path

OUT = Path(__file__).parent / 'results'


def assess(benchmark, regression, adapter):
    required = {'unchanged_catalog_sync', 'full_metadata_sync'}
    flows = {row['scenario']: row for row in benchmark['representative']}
    rows = [flows[name] for name in required if name in flows]
    checks = {
        'required_flows_present': required <= flows.keys(),
        'thirty_pairs': all(row['pairs'] >= 30 for row in rows),
        'representative_median_20_percent': all(row['python']['median_seconds'] > 0 and
            1 - row['rust']['median_seconds'] / row['python']['median_seconds'] >= .2 for row in rows),
        'positive_95_percent_interval': all(row['paired_bootstrap_95_percent'][0] > 0 for row in rows),
        'representative_records_equal': all(row['learning_records_equal_every_sample'] for row in rows),
        'requests_equal': all(row['python']['http_requests'] == row['rust']['http_requests'] for row in rows),
        'native_exercised': regression.get('native_calls', 0) > 0,
        'regression_suites_present': {'university', 'server'} <= regression.keys(),
        'regression_passed': all(row['total'] > 0 and row['errors'] == row['failures'] == 0
                                 for row in regression.values() if isinstance(row, dict)),
        'adapter_passed': adapter['python_adapter_tests'] >= 6 and adapter['rust_unit_tests'] >= 3
                          and adapter['errors'] == adapter['failures'] == 0,
    }
    return {'allow_expansion': all(checks.values()), 'checks': checks,
            'action': 'expand one local kernel, then remeasure' if all(checks.values()) else 'stop expansion; retain Python production backend',
            'candidate_remainder': ['section overview', 'course structure', 'visible-text normalization'],
            'note': 'Run benchmarks and tests from the current source before assessing; hashes are recorded with results.'}


if __name__ == '__main__':
    data = [json.loads((OUT / name).read_text(encoding='utf-8'))
            for name in ('benchmark.json', 'native-regression.json', 'adapter-tests.json')]
    decision = assess(*data)
    (OUT / 'decision.json').write_text(json.dumps(decision, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(decision, indent=2))
