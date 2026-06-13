# NL→Strategy Compiler — Design

**Date:** 2026-06-13
**Status:** Approved for planning
**Sub-project of:** Phase 2 "Agent Gateway" (NL→strategy first; conversational agent gateway is a later sub-project)

## Summary

Let a user describe a trading strategy in plain English (e.g. *"fade gaps over 3% on
high volume, exit at VWAP"*) and have the platform turn it into an executable strategy.
The compiler generates real Python strategy classes (best-of-N), validates and
sandbox-backtests each, ranks them with the platform's existing risk gates, and
**auto-promotes the single best passing candidate into paper trading** — no human click.
Live trading is hard-blocked structurally.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| What NL produces | **LLM-generated Python** strategy classes (not config-only, not a rule DSL) |
| Autonomy / trust boundary | **Full auto: backtest → paper**, if risk gates pass. Live trading hard-blocked. |
| Failure / iteration | **Best-of-N**: N candidates in parallel, promote the best that clears gates |
| Sandbox model | **AST allowlist + subprocess with `resource` rlimits** (kernel-enforced) |
| Package location | `backend/synthesis/` (separate from `backend/agent/`) |
| Risk gates | **Reuse** `backtest/tournament.py` `apply_gates()` / `rank_reports()` verbatim |
| LLM provider | Default **claude** via `research/llm_factory.build_llm_client` |
| Trigger surface (this sub-project) | `POST /api/synthesis` + CLI `python -m backend.synthesis`. No web UI yet. |

## Architecture

New package `backend/synthesis/`, one responsibility per module:

| Module | Responsibility | Depends on |
|---|---|---|
| `brief.py` | NL request → `StrategyBrief` (text, asset class, timeframe, constraints) | — |
| `generator.py` | Best-of-N: prompt LLM with the `base.py` contract + exemplar strategies + `indicators.py` API; return N `Candidate`s (source, class name, rationale) | `research/llm_factory.build_llm_client` |
| `validator.py` | AST allowlist scan + interface conformance; reject before any execution | `strategy/base.py` |
| `harness.py` | Adapter wrapping a candidate's `evaluate(ctx)` into the engine's `signal_fn(window)` shape; build `BarContext` | `strategy/base.py`, `backtest/engine.py` |
| `sandbox.py` | Run a validated candidate in a fresh rlimited subprocess; return JSON metrics or failure reason | `backtest/engine.run_backtest` |
| `ranker.py` | Sandbox metrics → `StrategyReport`; run `apply_gates()` + `rank_reports()`; return passing candidates, best first | `backtest/tournament.py` |
| `promoter.py` | Persist winner, register it, attach to the **paper** runner; constructs a paper-only execution graph | `strategy/registry.py`, `execution/paper.py` |
| `audit.py` | Append immutable JSONL record per run (prompt, provider+model, source hash, all stage results, promotion decision) | `store/` conventions |
| `pipeline.py` | Orchestrate brief → generate → validate → sandbox → rank → promote → audit. The one public entry point. | all of the above |
| `_worker.py` | Subprocess entry: import candidate in restricted namespace, run backtest, emit JSON | `sandbox.py` contract |

### Data flow

```
NL text
  → brief.py            → StrategyBrief
  → generator.py        → [Candidate × N]            (parallel LLM calls)
  → validator.py        → [Candidate(valid)]          (reject unsafe / non-conforming)
  → sandbox.py+harness  → [CandidateResult(metrics)]  (parallel rlimited subprocesses)
  → ranker.py           → [passing], best first       (reuse tournament gates)
  → promoter.py         → promote best → paper runner  (or "none passed")
  → audit.py            → JSONL record (always, every stage)
```

### Two strategy contracts (important)

The **live runner** uses `SignalStrategy.evaluate(ctx: BarContext) -> StrategySignal`
(`strategy/base.py`). The **backtest engine** uses `signal_fn(window) -> buy/sell flags`
where `signal_fn` receives `df.iloc[:i+1]` (no future data) (`backtest/engine.run_backtest`).
Generated code conforms to the **runner Protocol** (`evaluate`); `harness.py` adapts it to
the engine's `signal_fn` shape so backtest behavior matches eventual paper behavior.

## Safety model

### Layer 1 — `validator.py` (static, no execution)

Parse with `ast`, walk the tree, reject on any of:
- `Import` / `ImportFrom` (the harness injects the only allowed names)
- `While` (infinite-loop vector)
- `open` / `eval` / `exec` / `compile` / `__import__` / `globals` / `locals` / `input`
- dunder attribute access (`__class__`, `__bases__`, `__subclasses__`, `__globals__`, …)
- calls to any name not in an allowlist (pandas ops, `indicators.*`, safe builtins
  `len`/`min`/`max`/`abs`/`range`/`sum`/`sorted`/`enumerate`/`zip`)

Then conformance: the module defines exactly one class implementing
`evaluate(self, ctx) -> StrategySignal`. Any failure → candidate rejected, reason audited,
never executed.

### Layer 2 — `sandbox.py` (dynamic, isolated subprocess)

Each surviving candidate runs in a fresh `python -m backend.synthesis._worker` subprocess:
- `resource.setrlimit`: `RLIMIT_CPU` (~10s), `RLIMIT_AS` (address-space cap),
  `RLIMIT_FSIZE = 0` (no file writes), `RLIMIT_NPROC` (no forking)
- Scrubbed `env` — no `ALPACA_*` / `ANTHROPIC_*` / network credentials passed in
- Injected namespace: only `pandas`, `backend.strategy.base`, `backend.strategy.indicators`;
  `__builtins__` stripped to the safe subset
- Parent enforces a wall-clock timeout and kills the child on overrun
- Input: pickled bars + config via temp file/stdin; output: JSON metrics on stdout
- Crash / timeout / non-zero exit → candidate fails with reason, platform unaffected

### Structural paper-only guarantee (not a flag check)

- `promoter` is *constructed with* a `PaperExecutionAdapter` (`execution/paper.py`,
  hardcoded `paper=True`); it has **no code path** to `build_live_executor` or the `live`
  profile.
- Synthesis paper overlay built explicitly: `mode=test`, `alpaca_paper` / crypto sandbox,
  **`risk.enabled=true`, `guards.enabled=true`** (overriding the repo defaults of `false`).
- A unit test asserts nothing in `backend/synthesis/` reaches `execution/live.py`.
- Strategies are broker-free by contract (`BarContext` carries only data), so generated
  code structurally cannot touch an executor regardless.

## Persistence & registration

- Winning source → `backend/store/generated_strategies/<key>/<version>.py`
  (mirrors `store/tournament/`). Audit JSONL → `backend/store/synthesis/`.
- `registry.py` gains a supplemental `GENERATED_SIGNAL_STRATEGIES` dict + a loader that
  imports **only pre-validated** files from the store dir. Static maps untouched.
- **Hot promotion:** add `runner.Engine.reload_generated_strategies()` that merges promoted
  keys into `self.signal_strategies` from a JSON manifest the promoter updates — no
  `config.yaml` mutation, no restart. (Net-new mechanism; the engine reads strategies once
  at init today.)

## Error handling

- Per-candidate isolation: an LLM timeout, validation rejection, sandbox crash, or gate
  failure drops *that candidate* to a recorded failure; the run continues with survivors.
- A run where zero candidates pass returns a clean "none promoted" result listing every
  candidate's failure reason — not an exception.
- `llm_factory` silently chains providers (Ollama→Claude→Gemini→DeepSeek); the audit record
  **must** capture the actual provider + model + source hash used, or provenance is lost.

## Known constraints carried into the design

1. `mcp/tools.run_backtest` is hardcoded to 3 strategies — synthesis uses
   `backtest/engine.run_backtest` directly via the harness, not that endpoint.
2. `MAX_WINDOW=240` bars in the runner can starve session-aware strategies (gap/ORB style).
   The generator prompt steers away from logic needing more history than the live window
   provides; the backtest uses the same window discipline so paper behavior matches backtest.

## Testing

**Unit**
- `validator`: accepts a good candidate; rejects each unsafe class (import, `while`, `eval`,
  dunder access, disallowed call) and a non-conforming interface
- `sandbox`: kills a CPU-bomb and a memory-bomb candidate within limits; survives a crashing
  candidate without affecting the parent
- `harness`: `evaluate` ↔ `signal_fn` adapter equivalence on a known strategy
- `ranker`: uses the real `apply_gates` / `rank_reports`
- `promoter`: writes the manifest; a guard test asserts it cannot import `execution/live.py`

**Integration**
- Canned LLM stub returns a known-good + several known-bad candidates; full pipeline promotes
  the good one into a paper-only engine and audits all candidates
- Live-block test extends the existing `backend/tests/test_live_gating.py` pattern

## Out of scope (this sub-project)

- Conversational agent gateway / web chat UI (next sub-project; this exposes API + CLI only)
- Promotion to **live** trading (permanently hard-blocked for generated strategies)
- Portfolio/confirmation-strategy generation (signal strategies first; same pattern extends later)
- Agentic sequential refinement (chose best-of-N instead)

## Security review outcomes (post-implementation, Codex pass)

Applied hardening:
- Validator now blocks attribute pivots off the injected `pd`/`indicators` objects
  (`io`/`os`/`system`/`read_*`/`to_*`/`eval`/`query`/...), closing chains like
  `pd.io.common.os.system(...)` and `pd.read_csv("/proc/1/environ")` before exec.
- `/api/vibe/order/propose` refuses unless the platform is in paper mode (guards the
  IB/CCXT adapters whose live path isn't behind `execution/live.py`).
- `runner.Engine.reload_generated_strategies()` refuses to load generated strategies
  when `settings.live_trading` is set — paper-only is now mechanically enforced.
- Promoter constrains manifest paths to live under `GEN_DIR` (no path traversal).
- Generated strategies are always namespaced by manifest key (no regime-filter gaming).
- Silent-failure fixes: gateway `ok` mirrors the tool result; synthesis reports
  `ok=False` when candidates passed but promotion failed; per-candidate backtest is
  isolated so one bad candidate can't abort the run.

Residual risk (known limitations — NOT fully closed; track before enabling on untrusted input):
- **In-process execution of promoted code.** A promoted strategy's class body and
  `evaluate()` run in the runner process (inherent to any registered strategy). The
  AST validator (re-run on load) is the guard; it is not a true OS sandbox. The
  subprocess sandbox only isolates the *backtest/evaluation* phase. A persistent
  sandboxed execution worker for promoted strategies is a follow-up.
- **Sandbox is not network/seccomp isolated.** rlimits + scrubbed env + no-file-writes,
  but no network namespace. Acceptable because generation is driven by our own LLM
  prompt (not adversarial input) and env carries no secrets; revisit if briefs ever
  come from untrusted users. A constrained strategy DSL (vs. raw Python) would remove
  the class of risk entirely.

## Open items for the implementation plan

- Exact `RLIMIT_*` values and per-candidate wall-clock timeout (tune during build)
- N default and parallelism cap for generation + sandboxing
- OOS Sharpe floor for promotion beyond the existing gates (mitigates overfitting risk)
- Prompt template + which exemplar strategies to few-shot
