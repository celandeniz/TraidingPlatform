# Backtest & Validation Page — Design

**Date:** 2026-06-14
**Status:** Approved for planning
**Part of:** "Surface remaining backend in UI" (this is sub-project 1 of several;
the Automation page, Reports page, and Research additions are separate specs).

## Summary

The `/backtest` route is currently a `placeholder-page` stub. Build it into a real
**tabbed Backtest & Validation page** that surfaces the platform's validation
endpoints, and **extend `/api/backtest`** so it also runs on the daily data path
(the one that actually works with free yfinance data) across all registered
strategies — not just the 3 intraday ones.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| First UI slice | Backtest & Validation page |
| Layout | **Tabs** (radix `Tabs`, already a dependency) |
| Backtest data | **Extend `/api/backtest`** to support a daily timeframe + all registered strategies (reuse the tournament's `DailyBarCache` path) |
| Backend approach | **A — extend `/api/backtest` in place** (vs. a separate `/api/backtest/daily` endpoint, vs. a shared service module) |

## Architecture

### Frontend
Replace `frontend/app/backtest/page.tsx` (placeholder) with a tabbed page using
radix `Tabs`. New components under `frontend/components/core/backtest/`, one per
tab, each mirroring the existing card pattern (form state → fetch → result card;
`toast.error` on throw; branch on `ok`/`available`).

| Tab | Component | Endpoint |
|---|---|---|
| Backtest | `backtest-runner.tsx` | `POST /api/backtest` (timeframe incl. `1d`, all strategies) |
| Walk-Forward | `walk-forward.tsx` | `POST /api/walkforward` |
| Scenarios | `scenarios-grid.tsx` | `GET /api/backtest/scenarios` |
| Regime Select | `regime-select.tsx` | `POST /api/select` |
| Equity | `equity-curve.tsx` | `GET /api/equity_curve` |
| Greeks | `greeks-calc.tsx` | `GET /api/options/greeks` |

New typed helpers in `lib/api.ts` (`runBacktest`, `runWalkforward`, `getScenarios`,
`runSelect`, `getEquityCurve`, `getGreeks`) + result types in `lib/types.ts`.

### Backend (approach A — extend in place)
Make `timeframe == "1d"` (and `"1day"`/`"daily"`) a first-class path in the
`/api/backtest` handler:

```
backtest(body):
  if body.timeframe in DAILY_TFS:
      df = DailyBarCache(store/daily_cache).ensure([symbol]); df = cache.get(symbol)
  else:
      df = build_data_provider("equity").get_recent_bars(symbol, tf, bars)   # unchanged
  fn  = BACKTEST_STRATEGIES[body.strategy](params)   # all SIGNAL_STRATEGIES, not just 3
  res = run_backtest(df, fn, exits=ExitParams(tp, sl, ...), costs=CostModel(...))
  return { ...metrics..., ai_analysis (unchanged), available_strategies, timeframes }
```

- `BACKTEST_STRATEGIES`: a key→`generate` map covering every key in
  `strategy/registry.SIGNAL_STRATEGIES` (spike_fade, ema_momentum, donchian_breakout,
  rsi_reversion, macd_cross, vwap_reversion, keltner_breakout, atr_trend,
  orb_breakout, gap_go), each wired with sensible default params.
- The endpoint returns `available_strategies` and `timeframes` so the UI populates
  dropdowns from the backend (no hardcoded frontend list).
- Intraday path and the existing AI-analysis wiring are unchanged.

## Data flow (uniform per tab)

local form state → set `busy` → call `lib/api` helper → render a result card.
- Backtest: metrics (trades, win-rate, return %, profit factor, max DD, Sharpe,
  significance) + AI analysis text.
- Walk-Forward: per-fold IS→OOS rows showing honest degradation.
- Scenarios: the saved CSV grid as a sortable table.
- Regime Select: the tradable-whitelist result.
- Equity: a compact sparkline / points list from snapshots.
- Greeks: price + δ/γ/θ/ν/ρ computed from the query params (offline Black-Scholes).

## Error handling

Mirror existing cards: helpers throw on non-2xx → caught → `toast.error`. Payloads
with `ok:false` / `available:false` render an inline amber note:
- Equity → "snapshots disabled (snapshots.enabled=false)".
- Intraday backtest on the free Alpaca feed (≈5 bars) → "insufficient bars — try
  the daily timeframe".
One failing tab never affects another.

## Testing

- **Backend unit:** `/api/backtest` with `timeframe="1d"` runs a known strategy over
  a synthetic/cached daily frame and returns populated metrics; the intraday path
  still works; an unknown strategy returns a clean error. Sits beside
  `backend/tests/`; reuses the already-tested engine.
- **Frontend:** `tsc --noEmit` clean; each tab component renders its three states
  (idle / result / degraded), verified against the running API.
- No new test framework introduced.

## Out of scope (separate specs)
- Automation page (+ global kill switch), Reports page, Research additions
  (committee / copilot / news / vibe-strategy cards), exec-analytics surface.
