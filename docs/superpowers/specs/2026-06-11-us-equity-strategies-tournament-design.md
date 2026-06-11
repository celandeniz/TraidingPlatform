# US-Equity Strategy Expansion + Strategy Tournament — Phase 1 Design

**Date:** 2026-06-11
**Status:** Approved (brainstorming session)
**Role model:** [QuantDinger](https://github.com/brokermr810/QuantDinger) — local-first, agent-native quant platform

## Context & Goal

TraidingPlatform already matches QuantDinger on multi-broker execution (Alpaca/ccxt/IB),
backtesting + walk-forward, multi-LLM research, scanner, and paper-first safety. The gap
this phase closes: **proven US-equity strategies measured honestly**. "Best strategy" is
decided by an out-of-sample tournament, not by intuition.

This is Phase 1 of a three-phase roadmap:

1. **Phase 1 (this spec):** 6 new US-equity strategies (intraday + swing) + daily-bar data
   path + portfolio/pairs backtest engines + strategy tournament + `/tournament` UI.
2. **Phase 2 (future spec):** QuantDinger-parity AI layer — Agent Gateway with scoped
   tokens, MCP server, natural-language → strategy conversion.
3. **Phase 3 (future spec):** Trading UX polish — quick-trade panel, watchlists, richer
   charts, broker accounts page.

## Decisions Made

- **Horizon:** intraday (1–5m bars) AND swing (daily bars).
- **Ranking:** risk-adjusted composite — out-of-sample Sharpe primary, hard gates
  (max DD ≤ 20%, profit factor ≥ 1.3, ≥ 100 trades, statistical significance).
- **Architecture:** extend the existing strategy registry and backtest engine; one source
  of truth so the same strategy code backtests and trades live. No external backtest
  library, no premature dual-runtime refactor.

## Architecture

```
backend/
├── strategy/
│   ├── orb_breakout.py        # NEW: Opening Range Breakout (SignalStrategy, 1m bars)
│   ├── gap_go.py              # NEW: Gap-and-Go (SignalStrategy, 1m + prev daily close)
│   ├── earnings_drift.py      # NEW: PEAD (daily bars + earnings calendar)
│   ├── xs_momentum.py         # NEW: cross-sectional momentum (PortfolioStrategy)
│   ├── sector_rotation.py     # NEW: sector ETF rotation (PortfolioStrategy)
│   ├── pairs_statarb.py       # NEW: cointegrated pairs (PairStrategy)
│   └── base.py                # EXTEND: PortfolioStrategy + PairStrategy protocols
├── data/
│   ├── daily_cache.py         # NEW: daily-bar cache (Alpaca primary, yfinance fallback),
│   │                          #      parquet on disk, ~5y backfill, incremental update
│   └── earnings.py            # NEW: earnings calendar provider (yfinance), cached
├── backtest/
│   ├── portfolio_engine.py    # NEW: rank → hold-top-N rebalancing backtester
│   ├── pairs_engine.py        # NEW: spread-based two-leg backtester
│   └── tournament.py          # NEW: walk-forward orchestration, composite score + gates,
│                              #      persists ranked results JSON
└── web/                       # EXTEND: /api/tournament endpoints
frontend/app/tournament/       # NEW: leaderboard page
```

**Data flow.** `daily_cache` backfills ~5 years of daily OHLCV for the S&P 500 +
NASDAQ-100 universe, then updates incrementally. Intraday strategies use the existing
1m pipeline. The tournament runs every strategy through walk-forward validation
(existing `walkforward.py` for single-instrument; new splits for portfolio/pairs
engines), applies gates, ranks by OOS Sharpe, and writes a leaderboard JSON consumed
by the UI and (manually) by `config.yaml` strategy enablement.

**Live trading.** Tournament winners are enabled in `config.yaml` like existing
strategies — same registry, same paper-first defaults. Portfolio strategies emit target
weights; the existing OMS converts them into rebalance orders at daily cadence. Nothing
in Phase 1 weakens execution safety (`LIVE_TRADING=false`, `auto_trader.enabled=false`,
dry-run defaults all unchanged).

### New strategy protocols (`strategy/base.py`)

- `PortfolioStrategy`: `rebalance(ctx: UniverseContext) -> dict[symbol, weight]` —
  receives daily bars for the whole universe as of the rebalance date; returns target
  weights (cash = 1 − sum). No broker access; pure and testable like `SignalStrategy`.
- `PairStrategy`: `evaluate_pair(ctx: PairContext) -> PairSignal` — receives aligned
  daily bars for two legs + hedge ratio state; returns enter-long-spread /
  enter-short-spread / exit / none.

## Strategy Specifications

All parameters live in `config.yaml` under each strategy's key. Parameter values below
are defaults; the tournament selects parameters **only inside walk-forward training
windows** — never on test data.

### 1. Opening Range Breakout — `orb_breakout` (1m, intraday)

- Opening range = high/low of 09:30–09:45 ET (range minutes: param, default 15).
- Long on 1m close above range high; short below range low.
- Filters: relative volume ≥ 1.5× 20-day average; range width ≥ 0.3× ATR(14, daily).
- Stop: opposite side of the range. Take-profit: 2R (param). Hard exit 15:55 ET.
- One trade per symbol per day.

### 2. Gap-and-Go — `gap_go` (1m + previous daily close)

- Candidates gap ≥ 2% (param) above yesterday's close at the open.
- Long when price holds above VWAP and breaks the first 5-minute high.
- Skip if the gap fills early (price crosses back through the opening print).
- Stop below VWAP; trail with 1m EMA(9); exit by 15:55 ET.
- Mirrored short side (gap-down continuation) behind a flag, off by default.

### 3. Earnings Drift (PEAD) — `earnings_drift` (daily + earnings calendar)

- After an earnings report: if the stock gaps ≥ 5% up on report day with
  above-average volume, enter long at the next open.
- Hold 20 trading days (param); 10% stop.
- Symmetric short side behind a flag, off by default.

### 4. Cross-Sectional Momentum — `xs_momentum` (daily, PortfolioStrategy)

- Monthly rebalance: rank universe by 12-1 momentum (12-month return skipping the
  most recent month); hold top 20 equal-weight (params).
- Regime filter: 100% cash when SPY < its 200-day MA (param, default on).

### 5. Sector Rotation — `sector_rotation` (daily, PortfolioStrategy)

- Universe: 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU, XLC).
- Monthly: hold top 3 sectors by blended momentum (mean of 3-, 6-, and 12-month
  returns), equal weight.
- Same SPY 200-day cash filter.

### 6. Pairs Stat-Arb — `pairs_statarb` (daily, PairStrategy)

- Pair selection (re-run quarterly, inside walk-forward training only): within each
  sector, test high-correlation pairs for cointegration (Engle-Granger p < 0.05);
  keep top pairs by mean-reversion half-life.
- Spread z-score with rolling OLS hedge ratio. Enter |z| ≥ 2; exit z = 0;
  stop |z| ≥ 3.5 or 30 days. Legs sized dollar-neutral.

## Tournament

- **Validation:** rolling walk-forward; only out-of-sample windows count.
- **Hard gates (all must pass):** max drawdown ≤ 20%; profit factor ≥ 1.3;
  ≥ 100 trades (portfolio strategies: ≥ 24 rebalance periods); significance per
  existing `stats.significance` (p < 0.05, CI excludes 0).
- **Ranking:** gate-passers ranked by out-of-sample Sharpe. Gate-failers appear greyed
  out with the failed gate named — no survivorship hiding.
- **Persistence:** JSON under `backend/store/tournament/` with run timestamp, config
  hash, per-window detail.

### API

- `POST /api/tournament/run` — background task; progress over existing WebSocket hub.
- `GET /api/tournament/latest`, `GET /api/tournament/runs`.

### UI — `frontend/app/tournament/`

Leaderboard table (rank, strategy, OOS Sharpe, return, max DD, PF, trades, gate
badges) with an inline equity sparkline per strategy. Per-year window detail ships
in the run JSON; a richer drill-down/comparison chart is deferred to the Phase 3
UX-polish phase. DynamicsOps theme, shadcn/ui components, consistent with
existing pages.

## Error Handling

- **Data gaps:** `daily_cache` requires ≥ 3 years coverage per symbol; symbols below
  threshold are excluded and listed in the run report — never silently dropped.
- **Earnings feed failure:** `earnings_drift` reports "data unavailable" instead of
  running on partial data.
- **Strategy crash:** caught per-strategy; recorded as an error row on the
  leaderboard; never kills the tournament run.
- **Backfill rate limits:** batched requests, retry with backoff, resumable cache.

## Testing

TDD throughout:

- Per-strategy unit tests with synthetic bar fixtures (crafted gap day must trigger
  `gap_go`; non-gap day must not; etc.).
- Anti-lookahead tests for `portfolio_engine` (future-data-shuffle invariance, same
  pattern as the existing engine).
- `pairs_engine` tests with a synthetic cointegrated series.
- Tournament gate logic tests.
- API integration test per endpoint.

## Build Order

1. `daily_cache` + `earnings` provider
2. `orb_breakout` + `gap_go` on the existing engine
3. `portfolio_engine` + `xs_momentum` + `sector_rotation`
4. `earnings_drift`
5. `pairs_engine` + `pairs_statarb`
6. `tournament.py` + API endpoints
7. `/tournament` UI page

Each step lands separately with tests passing.

## Out of Scope (Phase 1)

- Agent Gateway / MCP server / NL-to-strategy (Phase 2).
- Quick-trade panel, watchlists, broker accounts UI (Phase 3).
- Multi-user RBAC/OAuth/billing (not needed for personal deployment).
- Options strategies; short-locate modeling; intraday portfolio strategies.
- Automatic enablement of tournament winners in live config (manual, deliberate step).
