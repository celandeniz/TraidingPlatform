# Fintech-repo integration roadmap

Seven open-sourced fintech repos were evaluated for fit with this platform
(Python, **closed 1m/3m/5m bars**, Alpaca + ccxt, ≤1 position per symbol, FastAPI
dashboard — not latency- or scale-bound). Three were integrated; one is a dev
nicety; **four were deliberately skipped** because they solve problems this
platform does not have. This file records *why*, and the specific condition that
would flip each from "skip" to "worth it" — so the decision is auditable, not lost.

## Integrated

| Repo | Firm | Where it lives |
|---|---|---|
| **perspective** | JPMorgan/FINOS | `backend/web/perspective_server.py` + `/static/perspective.html` (streaming dashboard tables). |
| **gs-quant** | Goldman | `backend/research/gs_analytics.py` — *concept* only; offline value is local Black-Scholes Greeks (gs-quant pricing needs Marquee auth we don't have). |
| **pyflyby** | D.E. Shaw | dev-only; see [pyflyby.md](pyflyby.md). |

Plus the **native** realistic execution/fill engine (`backend/execution/fills.py`,
`analytics.py`) — the actual "advanced & realistic transaction" win, which none of
the repos provide for Python.

## Skipped — and what would change that

### Jane Street — magic-trace
Process tracer using Intel Processor Trace for nanosecond, per-instruction CPU
profiling (OCaml tooling). It diagnoses latency in hot native code paths.
- **Why skip:** the platform acts on *closed 1-minute bars*. There is no
  microsecond-sensitive hot path to trace; the bottlenecks are I/O and model logic,
  not CPU instruction scheduling.
- **Revisit if:** a native low-latency execution path is built (see corral) and we
  need to shave microseconds — i.e. the platform pivots toward true HFT.

### Hudson River Trading — corral
Structured concurrency for C++20; foundational HFT infrastructure.
- **Why skip:** wrong language (we're Python) and wrong problem (no sub-millisecond
  order path). Python `asyncio` already covers our concurrency needs (bar streams,
  websocket fan-out).
- **Revisit if:** we build a separate C++ execution/market-data component for
  ultra-low-latency order handling. Then corral would structure its concurrency.

### Two Sigma — flint
Time-series as-of joins on Apache Spark/Scala for billions of rows.
- **Why skip:** unmaintained, needs a JVM + Spark cluster, and is overkill for our
  modest pandas datasets. The one capability we'd want — temporal-tolerance ("as-of")
  joins — is already native via `pandas.merge_asof` (and `polars.join_asof`).
- **Revisit if:** tick history grows to billions of rows across a cluster and pandas
  /polars on one box can no longer hold the working set. Even then, evaluate Polars +
  DuckDB before standing up Spark.

### BlackRock — lcso
Rust ADMM solver for large constrained convex optimization with piecewise-quadratic
terms. **No Python bindings.**
- **Why skip:** we hold ≤1 position per symbol across ~7–9 names — there is no
  large-scale portfolio-allocation problem to solve, and using lcso would require
  writing FFI/subprocess glue.
- **Revisit if:** the platform grows a portfolio-level capital-allocation layer over
  many assets with hard constraints. Try `cvxpy` (Python-native) first; reach for
  lcso only when problem size/structure genuinely breaks cvxpy's solvers.
