"""Per-module adoption with domain-specific non-regression guards."""
import json
from pathlib import Path

OUT = Path(__file__).parent / 'results'


def gain(row):
    return 100 * (1 - row['rust']['median_seconds'] / row['python']['median_seconds'])


def same(row):
    return row.get('outputs_equal') is True and row.get('pairs', 0) >= 30


def module_passes(rows):
    sizes_present = all(any(row['scenario'].endswith('_' + size) for row in rows) for size in ('100', '1000'))
    return sizes_present and all(same(row) and gain(row) >= 20
                                  and row['paired_bootstrap_95_percent'][0] > 0 for row in rows)


def non_regression(rows):
    return bool(rows) and all(same(row) and gain(row) >= -5
                             and row['paired_bootstrap_95_percent'][0] >= -5 for row in rows)


def assess(report, tests, experiments):
    suites = {'university', 'server'}
    suites_ok = suites <= tests.keys() and all(tests[name]['total'] > 0
        and tests[name]['errors'] == tests[name]['failures'] == 0 for name in suites if name in tests)
    experiments_ok = experiments['rust_unit_tests'] >= 6 and experiments['python_experiment_tests'] >= 27
    experiments_ok = experiments_ok and experiments['errors'] == experiments['failures'] == 0
    html_rows = report['representative']
    required = {'unchanged_catalog_sync', 'full_metadata_sync'}
    html_safe = required <= {row['scenario'] for row in html_rows} and non_regression(html_rows)
    if 'live' in report:
        live = report['live']
        html_safe = html_safe and live['outputs_equal'] and live['complete_fingerprints']['pairs'] >= 30 and gain(live['complete_fingerprints']) >= -5
        html_safe = html_safe and live['complete_fingerprints']['paired_bootstrap_95_percent'][0] >= -5
    modules = {}
    for name, rows, safe in (('activity', report['activity'], html_safe),
                              ('overview', report['overview'], html_safe),
                              ('concept', report['concept_rank'], non_regression(report['concept_flow']))):
        modules[name] = {'module_gain_passed': module_passes(rows), 'domain_non_regression': bool(safe),
                         'adopt': bool(suites_ok and experiments_ok and safe and module_passes(rows))}
    return dict(modules=modules, regression_passed=suites_ok, experiment_tests_passed=experiments_ok, overall_non_regression=bool(html_safe),
                full_rewrite_authorized=False, web_server_ported=False,
                policy='Module >=20% with positive paired interval; applicable flow no worse than 5%.')


if __name__ == '__main__':
    report = json.loads((OUT / 'partial-benchmark.json').read_text(encoding='utf-8'))
    tests = json.loads((OUT / 'partial-regression.json').read_text(encoding='utf-8'))
    experiments = json.loads((OUT / 'partial-tests.json').read_text(encoding='utf-8'))
    result = assess(report, tests, experiments)
    (OUT / 'partial-decision.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
