# Partial adoption phase

This phase follows the user's correction: a local kernel can be useful even when
network/DB/setup costs hide its benefit in the entire TLS workflow. The original
activity-pilot evidence and full-rewrite decision remain historical results.

## Separate decisions

- A module needs at least 20% median improvement and a positive 95% paired interval
  at medium and large representative inputs, including serialization/FFI/fallback.
- Outputs and failures must match; source filtering, permissions, scope checks and
  persistence remain under the existing Python contracts.
- The applicable whole flow must have median and lower 95% improvement bound above
  -5% (no more than 5% regression). Whole-flow +20% is not required for partial use.
- Activity and overview modules use TLS replay and captured-page fingerprint guards.
- Concept ranking additionally uses the SQLite-to-insights flow. A fast synthetic
  kernel alone is insufficient if integration worsens the actual concept operation.
- The actual loopback exam API is measured separately. A parser that is never called
  by that API cannot be credited with its response time. The HTTP server is not
  automatically rewritten or given weaker token/Origin checks.
- Full repository migration is not authorized by this partial decision. Reconsider
  the next costly local operation using profiles and the same per-module checks.

`partial_benchmark.py` measures the modules, concept DB flow, actual exam routes and
TLS replay in 30 paired samples. `assess_partial.py` produces per-module adoption.
The explicit `run.py` entry point activates only adopted modules and restores the
Python functions on exit. Missing/stale optional DLLs use the Python backend.
Normal Python entry points remain unchanged. Activate before starting request threads;
do not toggle global backends in the middle of serving requests.

Internal web/concept scope includes host-side semantic classification requests,
saved analysis JSON, source/evidence filtering, priority scoring, SQLite session
work and HTTP response serialization. Rust timings do not represent host-AI inference.
