# Rust activity-parser pilot

See [PLAN.md](PLAN.md) for the decision fixed before timing, and
[RUST_MIGRATION_RESULTS.md](../../RUST_MIGRATION_RESULTS.md) for measured results.

This is an experiment on `experiment/rust-core-refactor`. Production remains Python.
The pilot does not log in, fetch URLs, alter permissions or write the user DB.
`benchmark.py --live` separately reads current TLS course pages using an in-memory
session; only aggregate results leave memory. It never saves HTML or credentials.

## Build and validate

From the repository root, with Rust and Python 3.11 available:

```powershell
cargo build --release --locked --manifest-path experiments/rust-core/Cargo.toml
cargo test --release --locked --manifest-path experiments/rust-core/Cargo.toml
$env:PYTHONUTF8='1'
python -m unittest discover -s experiments/rust-core -p test_adapter.py
python -m unittest discover -s experiments/rust-core -p test_assess.py
python experiments/rust-core/benchmark.py
```

Use `python experiments/rust-core/benchmark.py --live` only when live reads are wanted.
This overwrites the experiment's aggregate benchmark JSON; keep prior measurements
when comparing environments. Compiler time and the first DLL load are excluded from
paired parser timings; DLL initialization/RSS are measured in separate fresh processes.

The initial run used a verified rustup installer and an isolated toolchain in the
parent workspace's `.rust-tools`, without changing the system PATH. This toolchain
and generated `target/` binaries are not committed. See `results/environment.json`
for the actual compiler, Python version, target and tested DLL SHA-256.
`Cargo.lock` pins the dependency graph.

## Provider regression with the experimental adapter

The recorded regression patches only `_ActivityParser` in the current Python
process. Child Python commands keep their normal Python backend. To reproduce from
the repository root, run the following Python through a UTF-8 Python process:

```python
import contextlib, json, pathlib, sys, unittest
from unittest.mock import patch
base = pathlib.Path('experiments/rust-core').resolve()
sys.path.insert(0, str(base))
from python_adapter import RustParser, parser_class
from providers import moodle_provider
native = RustParser()
results = {}
with (base / 'results/native-regression.txt').open('w', encoding='utf-8') as log:
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log), \
         patch.object(moodle_provider, '_ActivityParser', parser_class(native)):
        suites = [('university', unittest.TestLoader().discover('skills/university-agent/tests')),
                  ('server', unittest.TestLoader().loadTestsFromNames(['server.test_app', 'server.test_local']))]
        for name, suite in suites:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            results[name] = dict(total=result.testsRun,
                passed=result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
                errors=len(result.errors), failures=len(result.failures), skipped=len(result.skipped))
results.update(native_calls=native.calls, fallbacks=native.fallbacks)
(base / 'results/native-regression.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
assert native.calls > 0
assert all(row['errors'] == row['failures'] == 0 for row in results.values() if isinstance(row, dict))
```

After current results and adapter-test aggregates are present:

```powershell
python experiments/rust-core/assess.py
```

Expansion requires `allow_expansion: true`. The current result is false, so no
other parser or production module is migrated. If a future representative workload
passes, port one remaining local kernel, extend parity tests, and repeat the same
gate. A microbenchmark win alone is insufficient.

The adapter aggregate used by `assess.py` is stored in `results/adapter-tests.json`.
After a successful `cargo test`, regenerate that aggregate with this Python code
(the Rust count must match the successful Cargo test output):

```python
import json, pathlib, unittest
base = pathlib.Path('experiments/rust-core').resolve()
suite = unittest.TestLoader().discover(str(base), pattern='test_adapter.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = dict(rust_unit_tests=3, python_adapter_tests=result.testsRun,
               errors=len(result.errors), failures=len(result.failures))
(base / 'results/adapter-tests.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
assert result.wasSuccessful()
```

## Compatibility and limits

- `html5ever` tokenizes; it does not build a DOM that silently repairs activity nesting.
- Tokenizer recovery, invalid UTF-8/oversized input and surrogate strings use Python.
  Raw CR inside quoted URL attributes also uses Python to preserve URL bytes.
- Rust retains no response data between calls. The C ABI returns an owned buffer;
  the adapter frees it in `finally`, including JSON errors.
- The adapter's incremental interface reparses accumulated input; production callers
  currently feed whole pages. It is not a streaming-performance claim.
- The pilot was built/tested on Windows x64 GNU. macOS/Linux binaries, release
  bundles and full application startup have not been validated.

Primary implementation references: [html5ever tokenizer](https://docs.rs/html5ever/latest/html5ever/tokenizer/),
[Rust installation](https://rust-lang.org/tools/install/).
