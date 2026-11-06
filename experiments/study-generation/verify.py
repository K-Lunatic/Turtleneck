"""Run existing offline suites and save UTF-8 evidence for generation changes."""
import contextlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
results = Path(__file__).parent / 'results'
summary = {}
with (results / 'regression.txt').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        suites = [('university', unittest.TestLoader().discover(str(ROOT / 'skills/university-agent/tests'))),
                  ('server', unittest.TestLoader().loadTestsFromNames(['server.test_app', 'server.test_local']))]
        for name, suite in suites:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            summary[name] = dict(total=result.testsRun,
                passed=result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
                errors=len(result.errors), failures=len(result.failures), skipped=len(result.skipped))
(results / 'regression.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary, indent=2))
sys.exit(0 if all(row['errors'] == row['failures'] == 0 for row in summary.values()) else 1)
