# M7 Spike-Fade — Phase 2 Design (AI Decision & Research Layer)

**Date:** 2026-05-30
**Status:** Draft for user review
**Scope:** Phase 2 only — the AI-assisted decision/research layer that sits between
signal confirmation (Phase 1) and execution (Phase 3). Builds on the pluggable
strategy architecture already shipped.

**LLM provider:** Claude (Anthropic). **News/catalyst source:** Alpaca News API
(existing account). No other paid data API required for v1.

---

## 1. Goal & honest framing

Add fundamental + technical context and catalyst awareness to the engine, using AI
where it genuinely helps. Four layers, ordered by speed/cost/value:

1. **Catalyst Gate** — fast, mandatory, no-LLM. Suppresses fades into real catalysts.
2. **"Why is it moving?" Co-pilot** — slow, on-demand, Claude. Context panel.
3. **Fundamental Score** — medium, daily-cached, Claude. A confirmation dimension.
4. **Persona Consensus** — slowest, on-demand, Claude. Multi-analyst vote + manager.

**Honest limits (carried from Ek-1 §E1.9):** This layer **reduces risk, it does not
manufacture alpha.** In backtests even the filtered version did not beat buy-and-hold.
The LLM's job is to (a) kill bad trades (fade into a catalyst) and (b) add context — not
to be a signal generator. We keep that framing throughout. Persona consensus is the most
expensive and least proven layer; it is designed last and stays config-gated off by
default.

**Phase 2 stays paper-only.** No live orders. The decision layer outputs a `Decision`
object consumed by Phase 3's execution adapter later.

---

## 2. Where it fits in the pipeline

```
Signal (spike_fade)
  → Confirmation (bollinger)
  → AI Decision Layer  [NEW]
        Catalyst Gate (fast, mandatory)
        + Fundamental Score (confirmation dimension, optional)
        + Persona Consensus (optional, config-gated)
  → Decision (ALLOW/WITH_TREND_ONLY/SUPPRESS + side + rationale)
  → tape + dashboard  (Phase 3: execution)

Co-pilot runs OUT OF BAND: dashboard click → research → catalyst_update WS event.
```

Decision combine rule (Ek-1 §E1.5 compatible):

```
gate = SUPPRESS         → Decision.action = NONE   (tape reason: "catalyst")
gate = WITH_TREND_ONLY  → only trend-direction signal allowed; counter-trend fade dropped
gate = ALLOW            → signal proceeds; fundamental/persona attached as context/score
```

---

## 3. Module layout (added to backend/)

```
backend/
  research/
    __init__.py
    base.py             # shared types: CatalystVerdict, ResearchContext, FundamentalScore,
                        #   PersonaVote, Decision; LLM client protocol
    llm.py              # Claude client wrapper (prompt caching, retry, rate-limit, cost guard)
    news_provider.py    # Alpaca News + earnings-calendar adapter (provider-agnostic seam)
    catalyst_gate.py    # fast gate: earnings flag + news recency + gap/vol -> verdict
    fundamental_agent.py# best-effort fundamentals -> Claude summary -> -1..+1 score
    copilot_agent.py    # on-demand "why moving" (Claude + web search + news) -> summary
    decision_layer.py   # combines confirmation + gate + (fundamental/persona) -> Decision
    personas/
      __init__.py
      base.py           # Persona protocol: analyze(ctx) -> PersonaVote
      value.py          # value/quality lens
      momentum.py       # trend/momentum lens
      sentiment.py      # news/sentiment lens
      contrarian.py     # risk / counter-view lens
      portfolio_manager.py  # aggregates votes -> consensus recommendation
  tests/
    test_catalyst_gate.py
    test_decision_layer.py
    test_fundamental_agent.py   # with mocked LLM
    test_personas.py            # with mocked LLM
```

The `news_provider` and `llm` modules are behind interfaces (same adapter discipline as
`DataProvider`) so the news source or model can be swapped without touching logic.

---

## 4. Layer 1 — Catalyst Gate (fast, mandatory, NO LLM)

Runs on every fired+confirmed signal before it becomes a Decision. Sub-second; uses
flags only.

**Inputs:** recent Alpaca news for the symbol (timestamps), earnings-calendar proximity,
intraday gap% and volume z-score.

**Logic (all configurable):**
- Earnings today / within `earnings_block_days` (default 1) → `SUPPRESS`.
- Hot news within `news_recency_minutes` (default 30) → `WITH_TREND_ONLY` (or `SUPPRESS`
  if also large gap).
- Abnormal gap ≥ `gap_catalyst_pct` (default 2.5) + volume spike → `WITH_TREND_ONLY`.
- Otherwise → `ALLOW`.

**Output:** `CatalystVerdict{verdict, reasons[], news_count, earnings_in_days}`.

**Option-specific rule (Ek-1):** within `block_options_pre_earnings_days` of earnings,
options (CALL/PUT) disabled (IV-crush risk) — spot only if anything.

Backtest uses an offline gap/event proxy; live uses the real news/earnings feed. This is
documented as a known approximation.

---

## 5. Layer 2 — "Why is it moving?" Co-pilot (on-demand, Claude)

Triggered by a dashboard click on a symbol, not on the hot path.

**Flow:** gather recent news + price context → Claude (with web search for the "why") →
2–3 sentence summary + catalyst tag (`earnings | news | macro | none`) + last-3 headlines.

**Output:** `ResearchContext{summary, tag, headlines[], gate_decision, rationale}` →
broadcast as `catalyst_update` WS event → rendered in a dashboard "Why moving" card.

**Cost control:** per-symbol cache for `copilot.cache_minutes` (default 10); click-only;
never on every bar.

---

## 6. Layer 3 — Fundamental Score (medium, daily-cached, Claude)

Best-effort fundamentals for each symbol, summarised by Claude into a tilt score.

**Inputs:** whatever fundamentals Alpaca exposes (and a documented fallback to "neutral"
when coverage is missing — honest about Alpaca's limited fundamental depth).

**Output:** `FundamentalScore{score: -1..+1, label, rationale}` where + = long-friendly.
Attached to the signal event as a **confirmation dimension** (like Bollinger), surfaced in
the tape and dashboard. Cached daily per symbol.

**Not a hard gate** in v1 — it informs, it does not block. Whether it can veto is a
config flag (`fundamental.can_veto`, default false).

---

## 7. Layer 4 — Persona Consensus (slowest, on-demand, config-gated OFF by default)

Multi-analyst pattern (inspired by open-source ai-hedge-fund architecture; our own code,
no copying). Built LAST.

**Personas (each a Claude call with a distinct system prompt):**
- **Value** — quality/valuation lens.
- **Momentum** — trend/continuation lens.
- **Sentiment** — news/positioning lens.
- **Contrarian/Risk** — actively argues the other side (adversarial check).

Each returns `PersonaVote{side: long|short|pass, confidence: 0..1, rationale}`.

**Portfolio Manager** persona aggregates the votes → `Decision`-level recommendation +
combined rationale (weights configurable; contrarian acts as a veto-leaning voice).

**Cost control:** off by default (`personas.enabled: false`); on-demand only; never on the
hot path; results cached. Clearly the most expensive layer; value unproven — kept optional.

---

## 8. Decision object & combination

`decision_layer.decide(...)` produces:

```
Decision{
  action: SPOT_LONG | CALL | PUT | NONE,
  gate: ALLOW | WITH_TREND_ONLY | SUPPRESS,
  side: buy | sell | None,
  confirmations: {bollinger, fundamental?, personas?},
  rationale: str,
}
```

Mandatory inputs: signal side, regime, bollinger confirmation, catalyst gate. Optional:
fundamental score, persona consensus (only if enabled). Combination follows §2 rule;
gate is authoritative for suppression.

---

## 9. Config additions (config.yaml + .env)

```yaml
research:
  enabled: true
  news_provider: alpaca
  earnings_block_days: 1
  block_options_pre_earnings_days: 1
  news_recency_minutes: 30
  gap_catalyst_pct: 2.5
  fundamental:
    enabled: true
    can_veto: false
    cache_hours: 24
  copilot:
    enabled: true
    cache_minutes: 10
  personas:
    enabled: false          # off by default (cost); turn on deliberately
    weights: {value: 1.0, momentum: 1.0, sentiment: 1.0, contrarian: 1.2}
  llm:
    model: claude-opus-4-8  # or a cheaper Claude tier for high-volume layers
    max_calls_per_min: 20
    daily_cost_cap_usd: 5
```

`.env`: `ANTHROPIC_API_KEY=` (gitignored). All Claude calls go through `research/llm.py`
which enforces caching, rate limit, and the daily cost cap (hard stop when exceeded).

---

## 10. Dashboard additions (Phase 4 wiring, designed here)

- **"Why moving" card** per selected symbol: catalyst tag badge, 2–3 sentence summary,
  last-3 headlines, current gate decision + reason.
- **Signal grid:** new columns for gate verdict (ALLOW/SUPPRESS…) and fundamental score.
- WS event: `catalyst_update`.

---

## 11. Testing

- `catalyst_gate`: earnings-today → SUPPRESS; hot-news → WITH_TREND_ONLY; quiet → ALLOW
  (pure, no network).
- `decision_layer`: gate=SUPPRESS forces NONE; WITH_TREND_ONLY drops counter-trend fade;
  ALLOW passes through. (pure)
- `fundamental_agent` / `personas`: with a **mocked LLM client** (no live Claude calls in
  tests) — assert score parsing, vote aggregation, veto logic.
- `llm.py`: rate-limit and daily-cost-cap unit tests (mocked clock/counter).

No live Claude or live news calls in the test suite; those are exercised manually.

---

## 12. Build order (cost-controlled)

1. `news_provider` + `catalyst_gate` + `decision_layer` (no LLM) — immediate risk value.
2. `llm.py` (Claude wrapper w/ caching, rate-limit, cost cap).
3. `fundamental_agent` (Claude, daily cache).
4. `copilot_agent` + dashboard "why moving" card + `catalyst_update`.
5. `personas/*` LAST (config-gated off).

DoD per step mirrors Ek-1 §E1.8: a fade on an earnings-day/hot-news symbol is
auto-suppressed and the tape records "catalyst" as the reason.

---

## 13. Honest limits & risks

- AI layer reduces risk, does not produce alpha (backtest filtered < buy-and-hold).
- Alpaca fundamentals are shallow; fundamental score is best-effort, neutral when missing.
- LLM latency means the gate must stay non-LLM; deep "why" is context-only, not on the
  hot path.
- Persona consensus is unproven and the most expensive — off by default.
- Claude costs are real; the daily cost cap is a hard stop, and high-volume layers can use
  a cheaper Claude tier.
- News API coverage/recency varies; backtest gap-proxy ≠ live news gate.
```
