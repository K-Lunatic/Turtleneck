# Rust core experiment

Historical first-pilot criteria. Current partial adoption uses
[PARTIAL_PLAN.md](PARTIAL_PLAN.md); retain this plan with its original evidence.

Branch: `experiment/rust-core-refactor`, based on `c60d975`.
The `turtleneck` branch and the existing production Python backend are preserved.

The pilot ports `_ActivityParser` to an HTML5 tokenizer in Rust and calls it in the
same Python process through a small C ABI. Measured Rust times include UTF-8
encoding, FFI, Rust parsing/serialization, Python JSON decoding and fallback.
No login, cookies, rate limits, remote permissions or DB schema move in the pilot.

## Decision fixed before benchmarking

- Existing outputs and failure/recovery behavior must match, including URLs,
  restriction text, Unicode, malformed markup and concurrent calls.
- Use 30 paired samples with alternating order and a paired bootstrap interval.
- Representative unchanged-catalog and full-metadata replay flows must each improve
  median wall time by at least 20%, with the 95% bootstrap interval above zero.
- Also measure small/large parser workloads and real captured course pages. These
  isolated speedups do not by themselves authorize a wider rewrite.
- Report DLL initialization and process memory separately. Do not count compilation
  or HTTP-request reductions as a Rust runtime speedup.
- If the gate fails, retain the experiment/results and stop expansion. If it passes,
  profile remaining local parsing/normalization, migrate the next costly parser,
  and repeat parity and whole-flow gates before another expansion.
- Reuse the existing regression suite for scope freshness, account separation,
  permissions, retries, cleanup and SQLite contracts. No force push or main-branch
  edits. Commit locally on the experiment branch; do not push without a request.

The first remainder candidates are section-overview extraction, course-structure
extraction and visible-text normalization. Network waiting and SQLite's native
engine are not assumed to improve through a language change.
