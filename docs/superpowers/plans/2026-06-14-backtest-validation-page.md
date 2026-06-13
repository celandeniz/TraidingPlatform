# Backtest & Validation Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/backtest` placeholder with a real tabbed Backtest & Validation page that surfaces backtest / walk-forward / scenarios / regime-select / equity / greeks, and extend `/api/backtest` to run on the daily data path across all generic strategies.

**Architecture:** Backend — extract a small `run_one` helper (strategy map + data-source routing) so `/api/backtest` works on both intraday (Alpaca) and daily (`DailyBarCache`) timeframes and reports its `available_strategies`/`timeframes`. Frontend — a radix-`Tabs` page with one focused client component per tab, each following the existing card pattern (form → fetch → result), backed by new typed `lib/api` helpers.

**Tech Stack:** Python/FastAPI, pytest; Next.js (App Router) + React 19 + Tailwind + radix Tabs; `lib/api` `fetch` wrapper.

---

## File Structure

**Backend**
- Create: `backend/backtest/run_one.py` — strategy map + `run_one()` + `load_bars()` + `available_strategies()` + `DAILY_TIMEFRAMES`. One responsibility: run a single backtest from a key + data source.
- Create: `backend/tests/test_run_one.py` — unit tests for the helper.
- Modify: `backend/web/app.py` (the `/api/backtest` handler, ~lines 832-915) — use `run_one`/`load_bars`, add `available_strategies`/`timeframes` to the response.

**Frontend**
- Modify: `frontend/lib/types.ts` — result types.
- Modify: `frontend/lib/api.ts` — `runBacktest`, `runWalkforward`, `getScenarios`, `runSelect`, `getEquityCurve`, `getGreeks`.
- Create: `frontend/components/core/backtest/backtest-runner.tsx`
- Create: `frontend/components/core/backtest/walk-forward.tsx`
- Create: `frontend/components/core/backtest/scenarios-grid.tsx`
- Create: `frontend/components/core/backtest/regime-select.tsx`
- Create: `frontend/components/core/backtest/equity-curve.tsx`
- Create: `frontend/components/core/backtest/greeks-calc.tsx`
- Modify: `frontend/app/backtest/page.tsx` — assemble the Tabs.

---

## Task 1: Backend `run_one` helper (strategy map + data routing)

**Files:**
- Create: `backend/backtest/run_one.py`
- Test: `backend/tests/test_run_one.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_run_one.py
"""run_one backtest helper — strategy map + daily/intraday routing, no network."""
import numpy as np
import pandas as pd
import pytest

from backend.backtest.run_one import (
    DAILY_TIMEFRAMES, available_strategies, run_one,
)


def _df(n=400):
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n)
    close = 100 + 10 * np.sin(t / 8.0) + np.sin(t / 3.0)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + 0.5,
         "low": np.minimum(open_, close) - 0.5, "close": close,
         "volume": np.full(n, 1_000_000.0)}, index=idx)


def test_available_strategies_lists_generic_signals():
    keys = available_strategies()
    assert "rsi_reversion" in keys and "ema_momentum" in keys
    # intraday-session-only strategies are excluded from the generic runner
    assert "orb_breakout" not in keys and "gap_go" not in keys


def test_run_one_produces_metrics():
    res = run_one(_df(), "rsi_reversion", take_profit_pct=2.0, stop_loss_pct=1.5)
    assert res.error == "" and res.n_trades > 0


def test_run_one_unknown_strategy_raises():
    with pytest.raises(KeyError):
        run_one(_df(), "does_not_exist")


def test_daily_timeframes_set():
    assert "1d" in DAILY_TIMEFRAMES and "5m" not in DAILY_TIMEFRAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_run_one.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.backtest.run_one'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/backtest/run_one.py
"""Run ONE backtest from a strategy key, on intraday or daily bars.

Extracted so /api/backtest (and tests) share one code path. The strategy map
covers the bar-agnostic signal strategies; orb_breakout/gap_go are intraday-
session strategies and are intentionally excluded from this generic runner.
"""
from __future__ import annotations

from .engine import CostModel, ExitParams, run_backtest

DAILY_TIMEFRAMES = {"1d", "1day", "daily"}


def _strategy_fns() -> dict:
    from ..strategy.atr_trend import generate as atr_g
    from ..strategy.donchian_breakout import generate as donch
    from ..strategy.ema_momentum import generate as ema
    from ..strategy.keltner_breakout import generate as kelt
    from ..strategy.macd_cross import generate as macd_g
    from ..strategy.rsi_reversion import generate as rsi_g
    from ..strategy.spike_fade import generate as spike
    from ..strategy.vwap_reversion import generate as vwap_g

    return {
        "spike_fade": lambda df: spike(df, zscore_window=20, lookback_k=2, z_entry=2.0),
        "ema_momentum": lambda df: ema(df, fast=12, slow=26),
        "donchian": lambda df: donch(df, channel=20),
        "rsi_reversion": lambda df: rsi_g(df, period=14),
        "macd_cross": lambda df: macd_g(df, fast=12, slow=26),
        "vwap_reversion": lambda df: vwap_g(df, band_pct=1.0),
        "keltner_breakout": lambda df: kelt(df, period=20, mult=2.0),
        "atr_trend": lambda df: atr_g(df, period=20, k=1.5),
    }


def available_strategies() -> list:
    return list(_strategy_fns().keys())


def run_one(df, strategy: str, *, take_profit_pct: float = 2.0,
            stop_loss_pct: float = 1.5, scenario: str = ""):
    """Backtest one strategy on df. Raises KeyError for an unknown strategy."""
    fns = _strategy_fns()
    if strategy not in fns:
        raise KeyError(f"unknown strategy '{strategy}'; have {sorted(fns)}")
    return run_backtest(
        df, fns[strategy],
        exits=ExitParams(take_profit_pct, stop_loss_pct, 0.8, 90, True),
        costs=CostModel(1.0, 2.0), warmup=35, scenario=scenario)


def load_bars(symbol: str, timeframe: str, bars: int, provider):
    """Daily timeframes come from the (working) DailyBarCache; everything else
    from the live intraday provider."""
    if timeframe.lower() in DAILY_TIMEFRAMES:
        from ..data.daily_cache import DailyBarCache
        from ..settings import BACKEND_DIR

        cache = DailyBarCache(BACKEND_DIR / "store" / "daily_cache")
        cache.ensure([symbol.upper()], min_years=max(2, bars // 252))
        df = cache.get(symbol.upper())
        return df.tail(bars) if df is not None else df
    return provider.get_recent_bars(symbol.upper(), timeframe, bars)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_run_one.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/run_one.py backend/tests/test_run_one.py
git commit -m "feat(backtest): run_one helper (strategy map + daily/intraday routing)"
```

---

## Task 2: Wire `/api/backtest` to `run_one` + daily path + advertise strategies

**Files:**
- Modify: `backend/web/app.py` (handler at ~832-915)

- [ ] **Step 1: Replace the strategy map + `_run` body**

In `backend/web/app.py`, replace the function body of `async def backtest(body: BacktestBody)` from the `from ..backtest.analyze import analyze_results` import block down through the `fn = fns.get(...)` line and the `_run` closure with:

```python
    import asyncio as _a

    from ..backtest.analyze import analyze_results
    from ..backtest.run_one import available_strategies, load_bars, run_one

    def _run():
        df = load_bars(body.symbol, body.timeframe, body.bars, _provider)
        if df is None or len(df) == 0:
            raise ValueError("no bars returned for this symbol/timeframe")
        res = run_one(df, body.strategy, take_profit_pct=body.take_profit_pct,
                      stop_loss_pct=body.stop_loss_pct,
                      scenario=f"{body.symbol}|{body.timeframe}|{body.strategy}")
        analysis = analyze_results([res], _llm)
        return df, res, analysis
```

(Leave the `try/except` call, the `_epoch`/candles/markers/trades builders, and the final `return {...}` dict exactly as they are.)

- [ ] **Step 2: Add `available_strategies` + `timeframes` to the response**

In the final `return {` dict of `backtest(...)`, add these two keys (anywhere before the closing `}`):

```python
        "available_strategies": available_strategies(),
        "timeframes": ["1d", "1h", "15m", "5m"],
```

- [ ] **Step 3: Guard an unknown strategy cleanly**

`run_one` raises `KeyError` for an unknown strategy; the existing `except Exception` already converts it to `{"ok": False, "detail": ...}`. No change needed — verify by reading the `try/except` wrapping `_run`.

- [ ] **Step 4: Smoke-test the endpoint (daily path)**

Run (API not required — exercise the handler logic via run_one against the daily cache):
```bash
.venv/bin/python -c "
from backend.backtest.run_one import load_bars, run_one, available_strategies
from backend.brokers import build_data_provider
from backend.settings import get_settings, get_config
p=build_data_provider('equity', get_settings(), get_config())
df=load_bars('AAPL','1d',400,p); print('daily bars', 0 if df is None else len(df))
res=run_one(df,'rsi_reversion'); print('trades', res.n_trades, 'sharpe', round(res.sharpe,2))
print('strategies', available_strategies())
"
```
Expected: `daily bars 400` (approx), a trade count, and the 8-strategy list. (If yfinance is rate-limited, bars may be fewer; the point is non-zero + no crash.)

- [ ] **Step 5: Commit**

```bash
git add backend/web/app.py
git commit -m "feat(api): /api/backtest daily path + advertise available strategies/timeframes"
```

---

## Task 3: Frontend result types

**Files:**
- Modify: `frontend/lib/types.ts`

- [ ] **Step 1: Append the types** (at the end of `frontend/lib/types.ts`)

```typescript
export type BacktestResult = {
  ok: boolean;
  detail?: string;
  scenario?: string;
  symbol?: string;
  n_trades?: number;
  win_rate?: number;
  total_return_pct?: number;
  profit_factor?: number;
  max_drawdown_pct?: number;
  sharpe?: number;
  buy_hold_pct?: number;
  excess_vs_buy_hold?: number;
  exposure_pct?: number;
  significant?: boolean;
  significance_label?: string;
  p_value?: number;
  available_strategies?: string[];
  timeframes?: string[];
  ai?: { verdict?: string; caveats?: string[]; available?: boolean };
};

export type WalkForwardFold = {
  fold: number;
  chosen: string;
  is_return_pct: number;
  oos_return_pct: number;
  oos_buy_hold_pct: number;
  oos_excess_pct: number;
  oos_trades: number;
  oos_start: string;
  oos_end: string;
};

export type WalkForwardResult = {
  ok: boolean;
  detail?: string;
  symbol?: string;
  timeframe?: string;
  regime_filtered?: boolean;
  n_folds?: number;
  avg_is_return?: number;
  avg_oos_return?: number;
  avg_oos_excess?: number;
  degradation_pct?: number;
  oos_positive_folds?: number;
  oos_beat_bh_folds?: number;
  verdict?: string;
  folds?: WalkForwardFold[];
};

export type ScenarioRow = {
  scenario: string;
  n_trades: number;
  win_rate: number;
  total_return_pct: number;
  profit_factor: number;
  max_drawdown_pct: number;
  sharpe: number;
  buy_hold_pct: number;
  excess_vs_buy_hold: number;
};

export type ScenariosResult = { ok: boolean; detail?: string; count?: number; rows: ScenarioRow[] };

export type SelectVerdict = {
  symbol: string;
  tradable: boolean;
  avg_oos_return: number;
  oos_beat_bh_folds: number;
  n_folds: number;
  reason: string;
};

export type SelectResult = {
  ok: boolean;
  detail?: string;
  tradable?: string[];
  excluded?: string[];
  all_avg_oos?: number;
  tradable_avg_oos?: number;
  verdicts?: SelectVerdict[];
};

export type EquityPoint = { time?: string; equity?: number; [k: string]: unknown };
export type EquityCurveResult = { available: boolean; detail?: string; points: EquityPoint[] };

export type GreeksResult = {
  ok: boolean;
  detail?: string;
  [k: string]: unknown; // price, delta, gamma, theta, vega, rho, source (from gs_analytics.as_dict)
};
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: no new errors referencing `lib/types.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(web): types for backtest/walk-forward/scenarios/select/equity/greeks"
```

---

## Task 4: Frontend API helpers

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add imports** — extend the existing `import type { ... } from "@/lib/types";` block with:

```typescript
  BacktestResult,
  EquityCurveResult,
  GreeksResult,
  ScenariosResult,
  SelectResult,
  WalkForwardResult,
```

- [ ] **Step 2: Append the helpers** (end of `frontend/lib/api.ts`)

```typescript
export function runBacktest(body: {
  symbol: string;
  timeframe: string;
  strategy: string;
  take_profit_pct?: number;
  stop_loss_pct?: number;
  bars?: number;
}) {
  return api<BacktestResult>("/api/backtest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function runWalkforward(body: {
  symbol: string;
  timeframe: string;
  folds?: number;
  regime_filtered?: boolean;
  bars?: number;
}) {
  return api<WalkForwardResult>("/api/walkforward", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getScenarios() {
  return api<ScenariosResult>("/api/backtest/scenarios");
}

export function runSelect() {
  return api<SelectResult>("/api/select", { method: "POST", body: "{}" });
}

export function getEquityCurve(days = 7) {
  return api<EquityCurveResult>(`/api/equity_curve?days=${days}`);
}

export function getGreeks(p: {
  spot: number;
  strike: number;
  days: number;
  vol: number;
  rate?: number;
  call?: boolean;
}) {
  const q = new URLSearchParams({
    spot: String(p.spot),
    strike: String(p.strike),
    days: String(p.days),
    vol: String(p.vol),
    rate: String(p.rate ?? 0),
    call: String(p.call ?? true),
  });
  return api<GreeksResult>(`/api/options/greeks?${q.toString()}`);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(web): api helpers for backtest validation endpoints"
```

---

## Task 5: Backtest runner tab

**Files:**
- Create: `frontend/components/core/backtest/backtest-runner.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { runBacktest } from "@/lib/api";
import type { BacktestResult } from "@/lib/types";

const STRATEGIES = [
  "spike_fade", "ema_momentum", "donchian", "rsi_reversion",
  "macd_cross", "vwap_reversion", "keltner_breakout", "atr_trend",
];
const TIMEFRAMES = ["1d", "1h", "15m", "5m"];

export function BacktestRunner() {
  const [symbol, setSymbol] = useState("AAPL");
  const [timeframe, setTimeframe] = useState("1d");
  const [strategy, setStrategy] = useState("rsi_reversion");
  const [data, setData] = useState<BacktestResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runBacktest({ symbol: symbol.trim().toUpperCase(), timeframe, strategy }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "backtest failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest Runner</CardTitle>
        <CardDescription>
          No-lookahead backtest on real bars (costs in). Daily timeframe uses the
          cached yfinance path; intraday needs a live feed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            className="h-10 w-28 rounded-md border bg-background px-3 text-sm" placeholder="Symbol" />
          <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm">
            {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm">
            {(data?.available_strategies ?? STRATEGIES).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <Button onClick={run} disabled={busy || !symbol.trim()}>
            {busy ? "Running…" : "Run backtest"}
          </Button>
        </div>

        {data && !data.ok && (
          <p className="text-sm text-amber-600">{data.detail || "Backtest failed."}</p>
        )}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="outline">trades {number(data.n_trades, 0)}</Badge>
              <Badge variant="outline">win {number(data.win_rate, 1)}%</Badge>
              <Badge variant="outline">return {number(data.total_return_pct, 2)}%</Badge>
              <Badge variant="outline">PF {number(data.profit_factor, 2)}</Badge>
              <Badge variant="outline">maxDD {number(data.max_drawdown_pct, 1)}%</Badge>
              <Badge variant="outline">Sharpe {number(data.sharpe, 2)}</Badge>
              <Badge variant={data.significant ? "success" : "secondary"}>
                {data.significance_label || (data.significant ? "significant" : "not significant")}
              </Badge>
            </div>
            {data.ai?.available && (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium">AI:</span> {data.ai.verdict}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: no errors in this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/backtest-runner.tsx
git commit -m "feat(web): backtest runner tab"
```

---

## Task 6: Walk-Forward tab

**Files:**
- Create: `frontend/components/core/backtest/walk-forward.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { runWalkforward } from "@/lib/api";
import type { WalkForwardResult } from "@/lib/types";

export function WalkForward() {
  const [symbol, setSymbol] = useState("AAPL");
  const [folds, setFolds] = useState(4);
  const [data, setData] = useState<WalkForwardResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runWalkforward({ symbol: symbol.trim().toUpperCase(), timeframe: "5m", folds }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "walk-forward failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Walk-Forward Validation</CardTitle>
        <CardDescription>Out-of-sample folds; honest IS→OOS degradation. Needs intraday data.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            className="h-10 w-28 rounded-md border bg-background px-3 text-sm" placeholder="Symbol" />
          <input type="number" min={2} max={10} value={folds}
            onChange={(e) => setFolds(Number(e.target.value))}
            className="h-10 w-24 rounded-md border bg-background px-3 text-sm" />
          <Button onClick={run} disabled={busy || !symbol.trim()}>{busy ? "Running…" : "Run walk-forward"}</Button>
        </div>

        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Walk-forward failed."}</p>}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="outline">avg OOS {number(data.avg_oos_return, 2)}%</Badge>
              <Badge variant="outline">degradation {number(data.degradation_pct, 1)}%</Badge>
              <Badge variant="outline">OOS+ folds {number(data.oos_positive_folds, 0)}/{number(data.n_folds, 0)}</Badge>
              <Badge variant={data.oos_beat_bh_folds ? "success" : "secondary"}>{data.verdict}</Badge>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fold</TableHead><TableHead>Chosen</TableHead>
                  <TableHead className="text-right">IS %</TableHead>
                  <TableHead className="text-right">OOS %</TableHead>
                  <TableHead className="text-right">OOS excess %</TableHead>
                  <TableHead className="text-right">OOS trades</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.folds ?? []).map((f) => (
                  <TableRow key={f.fold}>
                    <TableCell>{f.fold}</TableCell>
                    <TableCell className="font-mono text-xs">{f.chosen}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.is_return_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_return_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_excess_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_trades, 0)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck** — `cd frontend && node_modules/.bin/tsc --noEmit` → no errors here.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/walk-forward.tsx
git commit -m "feat(web): walk-forward tab"
```

---

## Task 7: Scenarios grid tab

**Files:**
- Create: `frontend/components/core/backtest/scenarios-grid.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getScenarios } from "@/lib/api";
import type { ScenariosResult } from "@/lib/types";

export function ScenariosGrid() {
  const [data, setData] = useState<ScenariosResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getScenarios());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "scenarios failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Saved Scenario Grid</CardTitle>
        <CardDescription>The saved month grid (logs/backtest_month_30d.csv), ranked by excess vs buy-hold.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={load} disabled={busy}>{busy ? "Loading…" : "Load scenarios"}</Button>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "No saved grid."}</p>}
        {data && data.ok && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scenario</TableHead>
                <TableHead className="text-right">Trades</TableHead>
                <TableHead className="text-right">Win %</TableHead>
                <TableHead className="text-right">Return %</TableHead>
                <TableHead className="text-right">PF</TableHead>
                <TableHead className="text-right">Excess %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.slice(0, 100).map((r, i) => (
                <TableRow key={`${r.scenario}-${i}`}>
                  <TableCell className="font-mono text-xs">{r.scenario}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.n_trades, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.win_rate, 1)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.total_return_pct, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.profit_factor, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.excess_vs_buy_hold, 2)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck** — no errors here.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/scenarios-grid.tsx
git commit -m "feat(web): scenarios grid tab"
```

---

## Task 8: Regime Select tab

**Files:**
- Create: `frontend/components/core/backtest/regime-select.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { runSelect } from "@/lib/api";
import type { SelectResult } from "@/lib/types";

export function RegimeSelect() {
  const [data, setData] = useState<SelectResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runSelect());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "select failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Regime-Filtered Symbol Selection</CardTitle>
        <CardDescription>Walk-forward per universe symbol → a tradable whitelist. Needs intraday data; can take a while.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={run} disabled={busy}>{busy ? "Selecting…" : "Run selection"}</Button>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Selection failed."}</p>}
        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="success">tradable: {(data.tradable ?? []).join(", ") || "none"}</Badge>
              <Badge variant="secondary">excluded: {(data.excluded ?? []).length}</Badge>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead><TableHead>Tradable</TableHead>
                  <TableHead className="text-right">Avg OOS %</TableHead>
                  <TableHead className="text-right">Beat BH folds</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.verdicts ?? []).map((v) => (
                  <TableRow key={v.symbol}>
                    <TableCell className="font-semibold">{v.symbol}</TableCell>
                    <TableCell><Badge variant={v.tradable ? "success" : "secondary"}>{v.tradable ? "yes" : "no"}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{number(v.avg_oos_return, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(v.oos_beat_bh_folds, 0)}/{number(v.n_folds, 0)}</TableCell>
                    <TableCell className="max-w-[20rem] truncate text-muted-foreground">{v.reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck** — no errors here.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/regime-select.tsx
git commit -m "feat(web): regime-select tab"
```

---

## Task 9: Equity curve tab

**Files:**
- Create: `frontend/components/core/backtest/equity-curve.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getEquityCurve } from "@/lib/api";
import type { EquityCurveResult } from "@/lib/types";

export function EquityCurve() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<EquityCurveResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getEquityCurve(days));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "equity curve failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account Equity Curve</CardTitle>
        <CardDescription>From periodic snapshots (requires snapshots.enabled).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-end gap-2">
          <input type="number" min={1} max={90} value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-10 w-24 rounded-md border bg-background px-3 text-sm" />
          <Button onClick={load} disabled={busy}>{busy ? "Loading…" : "Load curve"}</Button>
        </div>
        {data && !data.available && <p className="text-sm text-amber-600">{data.detail || "Snapshots disabled."}</p>}
        {data && data.available && (
          <p className="text-sm text-muted-foreground">
            {data.points.length} points over {days}d. Latest:{" "}
            <span className="font-mono text-foreground">
              {JSON.stringify(data.points[data.points.length - 1] ?? {})}
            </span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck** — no errors here.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/equity-curve.tsx
git commit -m "feat(web): equity curve tab"
```

---

## Task 10: Greeks calculator tab

**Files:**
- Create: `frontend/components/core/backtest/greeks-calc.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getGreeks } from "@/lib/api";
import type { GreeksResult } from "@/lib/types";

export function GreeksCalc() {
  const [form, setForm] = useState({ spot: 100, strike: 100, days: 30, vol: 0.25, call: true });
  const [data, setData] = useState<GreeksResult | null>(null);
  const [busy, setBusy] = useState(false);

  const compute = async () => {
    setBusy(true);
    try {
      setData(await getGreeks(form));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "greeks failed");
    } finally {
      setBusy(false);
    }
  };

  const num = (k: "spot" | "strike" | "days" | "vol") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: Number(e.target.value) });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Options Greeks (Black-Scholes)</CardTitle>
        <CardDescription>Offline calculator. vol as a decimal (0.25 = 25%), days to expiry.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label className="grid gap-1">spot<input type="number" value={form.spot} onChange={num("spot")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">strike<input type="number" value={form.strike} onChange={num("strike")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">days<input type="number" value={form.days} onChange={num("days")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">vol<input type="number" step="0.01" value={form.vol} onChange={num("vol")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">type
            <select value={form.call ? "call" : "put"} onChange={(e) => setForm({ ...form, call: e.target.value === "call" })}
              className="h-10 rounded-md border bg-background px-3">
              <option value="call">call</option><option value="put">put</option>
            </select>
          </label>
          <Button onClick={compute} disabled={busy}>{busy ? "Computing…" : "Compute"}</Button>
        </div>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Failed."}</p>}
        {data && data.ok && (
          <div className="flex flex-wrap gap-2 text-sm">
            {Object.entries(data)
              .filter(([k]) => k !== "ok")
              .map(([k, v]) => (
                <Badge key={k} variant="outline">{k}: {typeof v === "number" ? v.toFixed(4) : String(v)}</Badge>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Typecheck** — no errors here.
- [ ] **Step 3: Commit**

```bash
git add frontend/components/core/backtest/greeks-calc.tsx
git commit -m "feat(web): options greeks tab"
```

---

## Task 11: Assemble the tabbed page

**Files:**
- Modify: `frontend/app/backtest/page.tsx`

- [ ] **Step 1: Replace the placeholder page**

```tsx
import { BacktestRunner } from "@/components/core/backtest/backtest-runner";
import { EquityCurve } from "@/components/core/backtest/equity-curve";
import { GreeksCalc } from "@/components/core/backtest/greeks-calc";
import { RegimeSelect } from "@/components/core/backtest/regime-select";
import { ScenariosGrid } from "@/components/core/backtest/scenarios-grid";
import { WalkForward } from "@/components/core/backtest/walk-forward";
import { PageTitle } from "@/components/shell/page-title";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { v: "backtest", label: "Backtest", el: <BacktestRunner /> },
  { v: "walkforward", label: "Walk-Forward", el: <WalkForward /> },
  { v: "scenarios", label: "Scenarios", el: <ScenariosGrid /> },
  { v: "select", label: "Regime Select", el: <RegimeSelect /> },
  { v: "equity", label: "Equity", el: <EquityCurve /> },
  { v: "greeks", label: "Greeks", el: <GreeksCalc /> },
];

export default function BacktestPage() {
  return (
    <>
      <PageTitle
        title="Backtest & Validation"
        description="Backtest runner, walk-forward, saved scenarios, regime selection, equity curve, and an offline options-greeks calculator."
      />
      <Tabs defaultValue="backtest">
        <TabsList className="flex flex-wrap">
          {TABS.map((t) => <TabsTrigger key={t.v} value={t.v}>{t.label}</TabsTrigger>)}
        </TabsList>
        {TABS.map((t) => <TabsContent key={t.v} value={t.v}>{t.el}</TabsContent>)}
      </Tabs>
    </>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: no errors (ignore any pre-existing `.next/types/*` cache-life noise).

- [ ] **Step 3: Commit**

```bash
git add frontend/app/backtest/page.tsx
git commit -m "feat(web): assemble tabbed Backtest & Validation page"
```

---

## Task 12: End-to-end verification

- [ ] **Step 1: Backend tests green**

Run: `.venv/bin/python -m pytest backend/tests/test_run_one.py -q`
Expected: PASS.

- [ ] **Step 2: Frontend builds**

Run: `cd frontend && node_modules/.bin/tsc --noEmit`
Expected: no non-`.next` errors.

- [ ] **Step 3: Serve + manual check**

Start API: `.venv/bin/python -m uvicorn backend.web.app:app --port 8765 &`
Start web: `cd frontend && pnpm exec next dev -p 3030 &`
Open `http://localhost:3030/backtest`. For each tab: Backtest (symbol AAPL, timeframe 1d, strategy rsi_reversion → metrics render); Walk-Forward / Regime Select (intraday — may show "no bars" with the free feed, no crash); Scenarios (loads grid or "run run_month first"); Equity ("snapshots disabled"); Greeks (Compute → δ/γ/θ/ν/ρ).

- [ ] **Step 4: Final commit (if any tweaks)**

```bash
git add -A && git commit -m "test(web): verify Backtest & Validation page end-to-end"
```

---

## Self-Review Notes (author)

- **Spec coverage:** 6 tabs (Tasks 5-10) + tabbed page (Task 11) + daily `/api/backtest` extension with `available_strategies`/`timeframes` (Tasks 1-2) — all spec sections covered.
- **Strategy map:** 8 generic strategies; orb_breakout/gap_go excluded (intraday-session-only) — matches the spec's "all registered strategies" intent for the *generic* runner and is asserted in `test_run_one.py`.
- **Type consistency:** `available_strategies()` (backend) ↔ `available_strategies?: string[]` (BacktestResult) ↔ dropdown in `backtest-runner.tsx`. `runSelect()` POSTs `"{}"` because `/api/select` takes no body. `getEquityCurve` returns `{available, points}` (no `ok`), handled by the `!data.available` branch.
- **No placeholders:** every step has full code/commands.
