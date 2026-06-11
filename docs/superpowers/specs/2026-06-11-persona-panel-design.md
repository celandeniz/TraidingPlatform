# Persona Panel (Investor-Legend Analysts) — Design

**Date:** 2026-06-11
**Status:** Approved (brainstorming session)
**Inspiration:** [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal)'s
37-agent investor-persona framework. FinceptTerminal is AGPL-3.0 with commercial
restrictions — **no code is copied**; this is a clean-room implementation of the
concept only, reusing our existing `Persona` infrastructure.

## Context & Goal

TraidingPlatform's LLM committee has 4 short-horizon personas (momentum,
contrarian, sentiment, value) that judge intraday setups from catalyst/news/
technical context. What's missing is the FinceptTerminal-style **fundamental
investor panel**: long-horizon, fundamentals-driven verdicts from distinct
investing philosophies, viewable per symbol and optionally feeding the
committee.

This is **Phase A** of a three-phase roadmap derived from the user's two
reference sources:

- **Phase A (this spec):** Persona Panel — 5 fundamentals-driven analyst
  personas + fundamentals data provider + `/api/panel/{symbol}` + research-page
  card + optional committee hook.
- **Phase B (future spec):** Quant + macro — VaR/portfolio-risk module, FRED /
  World Bank macro connectors (also upgrades the `macro_top_down` persona).
- **Phase C (future spec):** Polymarket prediction markets — py-clob-client
  data + paper trading as a new asset class (data-only first; wallet/live out
  of scope initially).

## Decisions Made

- Integration shape: **panel + committee hook** — the panel is independently
  viewable; it joins the existing committee only as ONE optional
  `persona_panel` analyst, default off. The committee flow is not restructured.
- Persona names are generic philosophy labels (no investor brand names in code
  or output).
- Reuse the existing `Persona` base and vote schema (side/confidence/rationale)
  — no new schema (YAGNI).

## Architecture

```
backend/
├── data/
│   └── fundamentals.py        # NEW: FundamentalsProvider — yfinance Ticker.info
│                              #   subset (<=15 metrics), JSON cache per symbol
│                              #   with 24h TTL, FundamentalsUnavailable typed error,
│                              #   injectable fetch_fn (no network in tests)
├── research/
│   ├── personas/legends.py    # NEW: 5 personas on the existing Persona base
│   └── panel.py               # NEW: PersonaPanel orchestrator + consensus +
│                              #   per-symbol result cache (JSON files under
│                              #   backend/store/panel_cache/, gitignored)
├── web/app.py                 # EXTEND: GET /api/panel/{symbol}
└── config.yaml                # NEW block: persona_panel (committee hook off)
frontend/
├── components/core/persona-panel.tsx   # NEW: panel card
└── app/research/...                    # EXTEND: render the card
```

### Data flow

`GET /api/panel/{symbol}` → panel checks its JSON cache (24h TTL; `?refresh=true`
bypasses) → on miss, builds ONE context string from:

1. **Fundamentals** (`fundamentals.py`): trailing PE, forward PE, PEG, P/B,
   ROE, profit margin, operating margin, debt-to-equity, free cash flow,
   revenue growth, earnings growth, market cap, dividend yield, beta,
   52w high/low. Missing fields rendered as `n/a`.
2. **Price summary** (from existing `daily_cache`, no new fetches): 1y return,
   annualized volatility, distance from 52w high/low.
3. **Headlines**: last 5 from the existing unified news provider.

Then runs the 5 personas sequentially (existing `ClaudeClient` — its rate
limits and daily cost caps apply), computes consensus, caches, returns.

### Personas (`legends.py`)

All extend `Persona` (same VOTE_SCHEMA). Lenses:

1. `value_moat` — durable competitive advantage, ROE >= 15%, low debt, FCF
   strength; says `pass` on rich valuations; ignores short-term charts.
2. `deep_value` — margin of safety: low P/B and P/E with a strong balance
   sheet; uses debt metrics to reject value traps.
3. `growth_garp` — growth at a reasonable price: PEG < 1.5, revenue growth,
   understandable business; skeptical of hype growth.
4. `macro_top_down` — sector/rate sensitivity and macro signals from headlines
   (Phase B upgrades this with FRED data).
5. `risk_chief` — argues AGAINST the strongest thesis: drawdown, valuation,
   concentration risk; biased toward `pass`.

Every system prompt instructs: when the context says fundamentals are
unavailable, vote `pass` with low confidence — never produce a confident
verdict from partial data. All prompts end with "Not investment advice."

### Consensus (`panel.py`, pure function)

Weighted vote: `score = Σ w_i × dir_i × confidence_i / Σ w_i` where dir is
+1 long / −1 short / 0 pass; weights from config (default equal). Verdict:
`long` if score >= 0.15, `short` if <= −0.15, else `pass`. Output:

```json
{"symbol": "AAPL", "verdict": "pass", "score": 0.08,
 "votes": [{"name": "value_moat", "side": "long", "confidence": 0.6,
            "rationale": "..."}, ...],
 "fundamentals_available": true, "generated_at": "...", "cached": false}
```

### API

- `GET /api/panel/{symbol}` — cached panel (24h). `?refresh=true` bypasses.
- 503 with detail `"llm unavailable"` when no LLM provider is configured
  (consistent with the existing copilot endpoint behavior).

### Committee hook

`config.yaml`:

```yaml
persona_panel:
  enabled: true            # the on-demand API/panel itself
  cache_ttl_hours: 24
  weights: {}              # per-persona overrides; default equal
  committee_hook: false    # when true, committee gains ONE persona_panel analyst
```

When `committee_hook: true`, `run_analysts` appends one `AnalystReport` built
from the panel consensus (served from cache if fresh; otherwise computed). The
committee call budget grows by at most the panel cost; with a fresh cache it
adds zero LLM calls.

### UI

`/research` page gains a "Persona Panel" card: symbol input reuses the page's
existing symbol selection; shows one chip per persona (name, side, confidence,
one-line rationale on hover/expand), a consensus badge, a refresh button, and
the "Not investment advice" footnote. Styling: existing shadcn/ui Card/Badge
conventions.

## Error handling

- Fundamentals fetch failure → context says `fundamentals: unavailable`;
  fundamental personas vote low-confidence `pass`; response carries
  `fundamentals_available: false`. The panel never fails outright for this.
- Persona LLM failure → existing `Persona.analyze` behavior (vote
  `pass` with `unavailable: <err>` rationale); consensus simply has fewer
  effective voters.
- Corrupt/stale panel cache → treated as cache miss, recomputed.
- No LLM configured → 503, no partial output.

## Testing

- `fundamentals.py`: fake fetch_fn — caching, TTL expiry, unavailable error,
  missing-field tolerance.
- `panel.py`: consensus math (pure, exhaustive: all-long, split, all-pass,
  weighted); orchestration with a fake client (no network).
- Committee hook: default-off (committee output unchanged); on → exactly one
  extra AnalystReport.
- API: monkeypatched panel; cache vs refresh behavior; 503 path.
- Frontend: `pnpm build` + manual check (house convention — no FE test runner).

## Out of scope (Phase A)

- FRED/World Bank connectors, VaR module (Phase B).
- Polymarket (Phase C).
- Backtesting persona verdicts; persona-driven order flow (panel is research
  surface + optional committee voice only — execution safety untouched).
- Parallel LLM calls; streaming output.
