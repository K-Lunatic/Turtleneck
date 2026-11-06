# Study generation optimization evidence

See [detailed record](../../STUDY_GENERATION_OPTIMIZATION_RESULTS.md) and
[report memo](../../STUDY_GENERATION_OPTIMIZATION_REPORT_MEMO.md).

`benchmark.py` drives the real StudySession/SQLite pipeline with deterministic host
fixtures, 30 final questions and 30 samples for one-file/four-file workloads. It
does not measure model inference. `before.json` was measured on `1a4f7e6`; preserve
it and use a separate checkout to reproduce that baseline.

```powershell
$env:PYTHONUTF8='1'
python experiments/study-generation/benchmark.py --output experiments/study-generation/results/after.json
python experiments/study-generation/verify.py
```

The actual Java2 observations in `results/live-java.json` are separate single host
executions. The 69.9-second observation includes HTTP API readiness but excludes
TLS download/preparation and browser rendering. It is not a randomized paired
inference benchmark or proof of the 30-60 second goal. One interrupted sample is
explicitly excluded. No original PDF, exam answers, user DB, course IDs or server
tokens are committed. Those remain in the parent workspace's private test folder.

For a fresh authorized real-source test, resolve the course/resource with the
normal runner, download only the requested file, use isolated source/session
copies, time request → host extraction → semantic review → assembly → HTTP ready,
and retain only aggregate timings/hashes. Keep model/context, settings, candidate
counts and cache status distinct when interpreting results. Host scripts may
assemble shared fields but must not manufacture questions without reading SOURCE.
