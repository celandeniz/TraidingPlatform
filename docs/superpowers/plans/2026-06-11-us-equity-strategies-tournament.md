# US-Equity Strategies + Tournament Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 proven US-equity strategies (intraday + swing), a daily-bar data layer, portfolio/pairs backtest engines, and an out-of-sample strategy tournament with a `/tournament` leaderboard UI.

**Architecture:** Extend the existing strategy registry and no-lookahead backtest engine (one source of truth: the same strategy code backtests and trades). New daily-bar CSV cache feeds swing strategies; new portfolio and pairs engines handle cross-sectional and two-leg strategies the single-instrument engine can't. A tournament orchestrator runs everything, applies hard gates, ranks by out-of-sample Sharpe, persists JSON, and serves it through FastAPI to a Next.js leaderboard page.

**Tech Stack:** Python 3 / FastAPI / pandas / pytest (backend); statsmodels (new, pairs only); yfinance (optional, daily-bar fallback + earnings); Next.js + shadcn/ui (frontend).

**Spec:** `docs/superpowers/specs/2026-06-11-us-equity-strategies-tournament-design.md`

**Conventions used throughout:**
- All commands run from repo root `/Users/denizcelan/Documents/GitHub/TraidingPlatform`.
- Python: `.venv/bin/python -m pytest backend/tests/... -q`
- Strategies follow the existing pattern: pure `generate(df, **params) -> dict` + thin adapter class, registered in `backend/strategy/registry.py`, params in `backend/config.yaml`.
- Walk-forward note: the new strategies ship with **fixed default parameters** (no in-sample parameter search), so their entire backtest period is out-of-sample by construction. The tournament reports per-year breakdowns for stability. If parameter search is added later it must go through `walkforward.py`'s IS/OOS split.

---

### Task 1: Engine support for per-signal exit overrides

ORB/gap/earnings strategies need trade-specific stops (range-based, VWAP-based, hold-N-days), not one global `ExitParams`. Let the signal dict optionally override exits per trade.

**Files:**
- Modify: `backend/backtest/engine.py`
- Test: `backend/tests/test_engine_signal_exits.py`

- [ ] **Step 1: Write the failing test**

```python
"""Per-signal exit overrides: a signal dict may carry stop_loss_pct /
take_profit_pct / time_stop_bars that override ExitParams for that trade only."""
import pandas as pd

from backend.backtest.engine import CostModel, ExitParams, run_backtest


def _df(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 14:30", periods=len(prices), freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": prices, "high": [p * 1.001 for p in prices],
         "low": [p * 0.999 for p in prices], "close": prices,
         "volume": [1000] * len(prices)},
        index=idx,
    )


def test_signal_stop_override_used_instead_of_exitparams():
    # Flat 100s, entry signal once warm, then a drop to 97 that would NOT hit the
    # wide default stop (10%) but MUST hit the per-signal 1% stop.
    prices = [100.0] * 40 + [97.0] * 5
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            return {"buy": True, "stop_loss_pct": 1.0, "take_profit_pct": 50.0}
        return {}

    res = run_backtest(df, sig, exits=ExitParams(take_profit_pct=50.0, stop_loss_pct=10.0),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].reason == "stop_loss"
    # stop at 1% below entry (~100), so exit ~99 — not the default 90
    assert res.trades[0].exit_px > 95.0


def test_signal_time_stop_override():
    prices = [100.0] * 60
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            return {"buy": True, "stop_loss_pct": 50.0, "take_profit_pct": 50.0,
                    "time_stop_bars": 3}
        return {}

    res = run_backtest(df, sig, exits=ExitParams(take_profit_pct=50.0, stop_loss_pct=50.0,
                                                 time_stop_bars=None),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].reason == "time_stop"
    assert res.trades[0].bars_held == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_engine_signal_exits.py -q`
Expected: FAIL (default stop 10% never hit / no time stop fires).

- [ ] **Step 3: Implement the override in `engine.py`**

In `run_backtest`, change the entry block (currently `pos = {"side": want, ...}`) to capture overrides:

```python
            if want is not None:
                # FILL AT NEXT BAR'S OPEN (i+1) — the key anti-lookahead rule.
                raw_entry = open_[i + 1]
                entry_px = _apply_cost(raw_entry, side_is_buy=(want == "long"), costs=costs)
                pos = {"side": want, "entry_idx": i + 1, "entry_px": entry_px,
                       "high_water": entry_px,
                       # per-signal exit overrides; fall back to global ExitParams
                       "stop_loss_pct": sig.get("stop_loss_pct", exits.stop_loss_pct),
                       "take_profit_pct": sig.get("take_profit_pct", exits.take_profit_pct),
                       "time_stop_bars": sig.get("time_stop_bars", exits.time_stop_bars)}
                i += 1
                continue
```

In the position-management block, replace every `exits.stop_loss_pct` with `pos["stop_loss_pct"]`, every `exits.take_profit_pct` with `pos["take_profit_pct"]`, and the time-stop line:

```python
            if exit_px is None and pos["time_stop_bars"] is not None and held >= pos["time_stop_bars"]:
                exit_px, reason = close[i], "time_stop"  # exit at this close
```

(`exits.trailing_stop_pct` and `exits.allow_short` stay global.)

- [ ] **Step 4: Run new + existing tests**

Run: `.venv/bin/python -m pytest backend/tests/test_engine_signal_exits.py backend/tests/ -q -k "engine or backtest"`
Expected: PASS (overrides work; existing engine behavior unchanged because fallbacks equal old globals).

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/engine.py backend/tests/test_engine_signal_exits.py
git commit -m "feat(backtest): per-signal exit overrides (stop/tp/time-stop)"
```

---

### Task 2: Daily-bar cache

**Files:**
- Create: `backend/data/daily_cache.py`
- Test: `backend/tests/test_daily_cache.py`

- [ ] **Step 1: Write the failing test**

```python
"""DailyBarCache: fetch-once CSV cache of daily OHLCV with coverage gating."""
from datetime import date, timedelta

import pandas as pd
import pytest

from backend.data.daily_cache import DailyBarCache


def _daily(n_days: int, end: date | None = None) -> pd.DataFrame:
    end = end or date(2026, 6, 10)
    idx = pd.bdate_range(end=end, periods=n_days, tz="UTC")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6},
        index=idx,
    )


def test_get_fetches_once_then_serves_from_disk(tmp_path):
    calls = []

    def fetch(symbol, start, end):
        calls.append(symbol)
        return _daily(800)

    cache = DailyBarCache(tmp_path, fetch_fn=fetch)
    df1 = cache.get("AAPL")
    df2 = cache.get("AAPL")
    assert calls == ["AAPL"]            # second call served from CSV
    assert len(df1) == 800 and len(df2) == 800
    assert list(df1.columns) == ["open", "high", "low", "close", "volume"]
    assert df1.index.tz is not None


def test_stale_cache_refetches_incrementally(tmp_path):
    old_end = date.today() - timedelta(days=30)

    def fetch_old(symbol, start, end):
        return _daily(800, end=old_end)

    cache = DailyBarCache(tmp_path, fetch_fn=fetch_old)
    cache.get("MSFT")

    fresh_calls = []

    def fetch_fresh(symbol, start, end):
        fresh_calls.append((start, end))
        return _daily(25)               # recent block

    cache2 = DailyBarCache(tmp_path, fetch_fn=fetch_fresh, max_stale_days=5)
    df = cache2.get("MSFT")
    assert fresh_calls, "stale cache must trigger a refetch"
    assert df.index.max().date() >= date.today() - timedelta(days=7)
    assert df.index.is_monotonic_increasing and df.index.is_unique


def test_ensure_reports_excluded_symbols(tmp_path):
    def fetch(symbol, start, end):
        if symbol == "NEWIPO":
            return _daily(100)          # < 3 years
        if symbol == "BROKEN":
            raise RuntimeError("api down")
        return _daily(1300)

    cache = DailyBarCache(tmp_path, fetch_fn=fetch)
    rep = cache.ensure(["AAPL", "NEWIPO", "BROKEN"], min_years=3)
    assert rep.included == ["AAPL"]
    assert "NEWIPO" in rep.excluded and "insufficient" in rep.excluded["NEWIPO"]
    assert "BROKEN" in rep.excluded and "api down" in rep.excluded["BROKEN"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_daily_cache.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.data.daily_cache`.

- [ ] **Step 3: Implement `backend/data/daily_cache.py`**

```python
"""Daily OHLCV cache for the swing/portfolio strategies.

One CSV per symbol under the cache dir. Fetch is pluggable: pass fetch_fn
(symbol, start, end) -> DataFrame for tests; default tries Alpaca (alpaca-py)
then yfinance. Bars: open/high/low/close/volume, tz-aware UTC DatetimeIndex,
oldest..newest. Pure pandas otherwise — no network in tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

FetchFn = Callable[[str, date, date], pd.DataFrame]
COLUMNS = ["open", "high", "low", "close", "volume"]
TRADING_DAYS_PER_YEAR = 252


@dataclass
class CoverageReport:
    included: list = field(default_factory=list)
    excluded: dict = field(default_factory=dict)   # symbol -> reason


def _fetch_alpaca(symbol: str, start: date, end: date) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(
        os.environ["APCA_API_KEY_ID"], os.environ["APCA_API_SECRET_KEY"]
    )
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=start, end=end)
    bars = client.get_stock_bars(req).df
    if bars.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = bars.reset_index().set_index("timestamp")[COLUMNS]
    return df.tz_convert("UTC") if df.index.tz else df.tz_localize("UTC")


def _fetch_yfinance(symbol: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(symbol, start=start, end=end + timedelta(days=1),
                      auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.rename(columns=str.lower)[COLUMNS]
    return df.tz_localize("UTC") if df.index.tz is None else df.tz_convert("UTC")


def default_fetch(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Alpaca primary, yfinance fallback (spec: Error Handling / data sources)."""
    try:
        df = _fetch_alpaca(symbol, start, end)
        if not df.empty:
            return df
    except Exception:
        pass
    return _fetch_yfinance(symbol, start, end)


class DailyBarCache:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None,
                 *, max_stale_days: int = 3):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or default_fetch
        self.max_stale_days = max_stale_days

    def _path(self, symbol: str) -> Path:
        return self.dir / f"{symbol.upper()}.csv"

    def _load(self, symbol: str) -> Optional[pd.DataFrame]:
        p = self._path(symbol)
        if not p.exists():
            return None
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df[COLUMNS]

    def _save(self, symbol: str, df: pd.DataFrame) -> None:
        df.to_csv(self._path(symbol))

    def get(self, symbol: str, *, years: int = 5) -> pd.DataFrame:
        """Cached daily bars, refreshed incrementally when stale."""
        today = date.today()
        df = self._load(symbol)
        if df is None or df.empty:
            df = self.fetch_fn(symbol, today - timedelta(days=int(years * 365.25)), today)
            df = self._normalize(df)
            self._save(symbol, df)
            return df
        last = df.index.max().date()
        if (today - last).days > self.max_stale_days:
            fresh = self._normalize(self.fetch_fn(symbol, last, today))
            df = pd.concat([df, fresh])
            df = df[~df.index.duplicated(keep="last")].sort_index()
            self._save(symbol, df)
        return df

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df = df[COLUMNS].sort_index()
        return df[~df.index.duplicated(keep="last")]

    def ensure(self, symbols: list[str], *, years: int = 5,
               min_years: int = 3) -> CoverageReport:
        """Backfill all symbols; exclude (with reason) any below min coverage.
        Spec rule: never silently dropped."""
        rep = CoverageReport()
        need = min_years * TRADING_DAYS_PER_YEAR
        for sym in symbols:
            try:
                df = self.get(sym, years=years)
            except Exception as exc:           # noqa: BLE001 — reported, not hidden
                rep.excluded[sym] = f"fetch failed: {exc}"
                continue
            if len(df) < need:
                rep.excluded[sym] = f"insufficient history: {len(df)} rows < {need}"
            else:
                rep.included.append(sym)
        return rep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_daily_cache.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/data/daily_cache.py backend/tests/test_daily_cache.py
git commit -m "feat(data): daily-bar CSV cache with coverage gating"
```

---

### Task 3: Earnings calendar provider

**Files:**
- Create: `backend/data/earnings.py`
- Test: `backend/tests/test_earnings.py`

- [ ] **Step 1: Write the failing test**

```python
"""EarningsCalendar: cached earnings dates; explicit failure, never partial data."""
import pandas as pd
import pytest

from backend.data.earnings import EarningsCalendar, EarningsUnavailable


def test_get_dates_fetches_once_and_caches(tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return [pd.Timestamp("2026-01-28"), pd.Timestamp("2026-04-30")]

    cal = EarningsCalendar(tmp_path, fetch_fn=fetch)
    d1 = cal.get_dates("AAPL")
    d2 = cal.get_dates("AAPL")
    assert calls == ["AAPL"]
    assert d1 == d2 == [pd.Timestamp("2026-01-28"), pd.Timestamp("2026-04-30")]


def test_fetch_failure_raises_unavailable(tmp_path):
    def fetch(symbol):
        raise RuntimeError("rate limited")

    cal = EarningsCalendar(tmp_path, fetch_fn=fetch)
    with pytest.raises(EarningsUnavailable):
        cal.get_dates("MSFT")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_earnings.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.data.earnings`.

- [ ] **Step 3: Implement `backend/data/earnings.py`**

```python
"""Earnings calendar provider — yfinance-backed, JSON-cached per symbol.

Spec rule: on fetch failure raise EarningsUnavailable so earnings_drift reports
"data unavailable" instead of trading on partial data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

FetchFn = Callable[[str], list]


class EarningsUnavailable(RuntimeError):
    pass


def _fetch_yfinance(symbol: str) -> list:
    import yfinance as yf

    df = yf.Ticker(symbol).get_earnings_dates(limit=40)
    if df is None or df.empty:
        return []
    return [pd.Timestamp(ts).tz_localize(None).normalize() for ts in df.index]


class EarningsCalendar:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or _fetch_yfinance

    def _path(self, symbol: str) -> Path:
        return self.dir / f"{symbol.upper()}_earnings.json"

    def get_dates(self, symbol: str) -> list[pd.Timestamp]:
        """Past + scheduled earnings dates (naive, normalized), oldest..newest."""
        p = self._path(symbol)
        if p.exists():
            iso = json.loads(p.read_text())
            return [pd.Timestamp(s) for s in iso]
        try:
            dates = sorted(pd.Timestamp(d).tz_localize(None).normalize()
                           if pd.Timestamp(d).tzinfo else pd.Timestamp(d).normalize()
                           for d in self.fetch_fn(symbol))
        except Exception as exc:  # noqa: BLE001 — converted to a typed failure
            raise EarningsUnavailable(f"{symbol}: {exc}") from exc
        p.write_text(json.dumps([d.date().isoformat() for d in dates]))
        return dates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_earnings.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/data/earnings.py backend/tests/test_earnings.py
git commit -m "feat(data): cached earnings calendar provider"
```

---

### Task 4: Opening Range Breakout strategy

**Files:**
- Create: `backend/strategy/orb_breakout.py`
- Modify: `backend/strategy/registry.py`
- Modify: `backend/config.yaml` (strategy params; NOT added to active `strategies.signal` — tournament decides enablement)
- Test: `backend/tests/test_orb_breakout.py`

- [ ] **Step 1: Write the failing test**

```python
"""ORB: break of the 09:30-09:45 ET opening range, with range-based exits."""
import pandas as pd

from backend.strategy.orb_breakout import generate


def _session(closes_by_minute: list[float], day: str = "2026-06-08") -> pd.DataFrame:
    """1m bars starting 09:30 ET. closes drive OHLC (tight bars)."""
    idx = pd.date_range(f"{day} 09:30", periods=len(closes_by_minute),
                        freq="1min", tz="America/New_York").tz_convert("UTC")
    c = pd.Series(closes_by_minute, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.05,
                         "low": c - 0.05, "close": c, "volume": 10_000.0})


def test_breakout_above_range_fires_buy_with_range_exits():
    # 15 min flat 100.0..100.4 (range hi ~100.45 incl wick), then a bar closing 101.0
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [101.0]
    df = _session(closes)
    sig = generate(df, range_minutes=15, min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is True and sig["sell"] is False
    assert sig["stop_loss_pct"] > 0          # stop = far side of the range
    assert sig["take_profit_pct"] >= 2 * sig["stop_loss_pct"] * 0.99  # ~2R
    assert sig["time_stop_bars"] > 0          # bars until 15:55 ET


def test_inside_range_no_signal():
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [100.2]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False and sig["sell"] is False


def test_during_range_formation_no_signal():
    closes = [100.0, 100.1, 105.0]            # only 3 minutes in — range not formed
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False and sig["sell"] is False


def test_breakdown_below_range_fires_sell():
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [99.0]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["sell"] is True and sig["buy"] is False


def test_only_first_breakout_bar_fires():
    # bar 16 breaks out; bar 17 is still above the range but must NOT re-fire
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [101.0, 101.2]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_orb_breakout.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.strategy.orb_breakout`.

- [ ] **Step 3: Implement `backend/strategy/orb_breakout.py`**

```python
"""Opening Range Breakout (ORB) — classic US-equity intraday strategy.

Opening range = high/low of the first `range_minutes` after 09:30 ET. Long on the
FIRST 1m close above the range high (short below range low). Stop at the far side
of the range, take-profit at `risk_reward` x R, hard time-exit at 15:55 ET — all
emitted as per-signal exit overrides (engine.py Task 1).

Filters (each auto-skipped when the window lacks history to compute it):
  * relative volume: today's cumulative volume >= min_rel_volume x the average
    cumulative volume at the same minute over prior sessions in the window.
  * range width >= min_range_atr x daily ATR(14) resampled from prior sessions.

Pure logic in generate(df); OrbBreakoutStrategy adapts to SignalStrategy.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal

SESSION_TZ = "America/New_York"
OPEN = "09:30"
LAST_ENTRY = "15:30"   # no fresh entries after this
HARD_EXIT = "15:55"


def _et(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.tz_convert(SESSION_TZ)
    return out


def generate(
    df: pd.DataFrame,
    *,
    range_minutes: int = 15,
    risk_reward: float = 2.0,
    min_rel_volume: float = 1.5,
    min_range_atr: float = 0.3,
) -> dict:
    """Evaluate ORB on the LAST closed 1m bar of df. Needs OHLCV, tz-aware index."""
    no = {"buy": False, "sell": False}
    if len(df) < range_minutes + 1:
        return no
    et = _et(df)
    last_ts = et.index[-1]
    day = et[et.index.date == last_ts.date()]
    session = day.between_time(OPEN, "16:00")
    if len(session) < range_minutes + 1:
        return no                       # range still forming (or no session data)
    if last_ts.time() > pd.Timestamp(f"2000-01-01 {LAST_ENTRY}").time():
        return no                       # too late in the day to enter

    rng = session.iloc[:range_minutes]
    range_hi = float(rng["high"].max())
    range_lo = float(rng["low"].min())
    close = float(session["close"].iloc[-1])
    prev_close = float(session["close"].iloc[-2])

    # FIRST-cross only: previous bar inside the range, this bar's close outside.
    buy = prev_close <= range_hi and close > range_hi
    sell = prev_close >= range_lo and close < range_lo
    if not (buy or sell):
        return no

    prior = et[et.index.date < last_ts.date()]
    prior_days = sorted(set(prior.index.date))

    # --- relative-volume filter (needs >= 3 prior sessions) ---
    if min_rel_volume > 0 and len(prior_days) >= 3:
        cum_today = float(session["volume"].sum())
        t = last_ts.time()
        prior_cums = []
        for d in prior_days:
            ds = prior[prior.index.date == d].between_time(OPEN, "16:00")
            ds = ds[ds.index.time <= t]
            if len(ds):
                prior_cums.append(float(ds["volume"].sum()))
        if prior_cums:
            avg = sum(prior_cums) / len(prior_cums)
            if avg > 0 and cum_today < min_rel_volume * avg:
                return no

    # --- range-width vs daily ATR filter (needs >= 15 prior sessions) ---
    if min_range_atr > 0 and len(prior_days) >= 15:
        daily = prior.groupby(prior.index.date).agg(
            high=("high", "max"), low=("low", "min"), close=("close", "last"))
        prev_c = daily["close"].shift(1)
        tr = pd.concat([daily["high"] - daily["low"],
                        (daily["high"] - prev_c).abs(),
                        (daily["low"] - prev_c).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        if pd.notna(atr) and (range_hi - range_lo) < min_range_atr * atr:
            return no

    # --- per-signal exits (engine overrides) ---
    if buy:
        stop_pct = (close - range_lo) / close * 100.0
    else:
        stop_pct = (range_hi - close) / close * 100.0
    if stop_pct <= 0:
        return no
    bars_to_exit = max(1, int((pd.Timestamp(f"{last_ts.date()} {HARD_EXIT}",
                                            tz=SESSION_TZ) - last_ts).total_seconds() // 60))
    return {
        "buy": bool(buy), "sell": bool(sell),
        "stop_loss_pct": round(stop_pct, 4),
        "take_profit_pct": round(risk_reward * stop_pct, 4),
        "time_stop_bars": bars_to_exit,
        "range_hi": range_hi, "range_lo": range_lo,
    }


class OrbBreakoutStrategy:
    name = "orb_breakout"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("orb_breakout", {})
        res = generate(
            ctx.window,
            range_minutes=p.get("range_minutes", 15),
            risk_reward=p.get("risk_reward", 2.0),
            min_rel_volume=p.get("min_rel_volume", 1.5),
            min_range_atr=p.get("min_range_atr", 0.3),
        )
        side = "buy" if res.get("buy") else "sell" if res.get("sell") else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0, meta=res)
```

- [ ] **Step 4: Register + config**

In `backend/strategy/registry.py` add the import and map entry:

```python
from .orb_breakout import OrbBreakoutStrategy
```

```python
    "orb_breakout": OrbBreakoutStrategy,
```

In `backend/config.yaml`, after the `vwap_reversion:` block add:

```yaml
# Intraday US-equity strategies (tournament candidates; enable in strategies.signal
# only after they pass tournament gates)
orb_breakout:
  range_minutes: 15
  risk_reward: 2.0
  min_rel_volume: 1.5
  min_range_atr: 0.3
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest backend/tests/test_orb_breakout.py backend/tests/ -q`
Expected: PASS, full suite green.

- [ ] **Step 6: Commit**

```bash
git add backend/strategy/orb_breakout.py backend/strategy/registry.py backend/config.yaml backend/tests/test_orb_breakout.py
git commit -m "feat(strategy): opening range breakout (ORB)"
```

---

### Task 5: Gap-and-Go strategy

**Files:**
- Create: `backend/strategy/gap_go.py`
- Modify: `backend/strategy/registry.py`
- Modify: `backend/config.yaml`
- Test: `backend/tests/test_gap_go.py`

- [ ] **Step 1: Write the failing test**

```python
"""Gap-and-Go: gap >= 2% over prior session close, holds above VWAP, breaks the
first-5-minute high. Prior session close is derived from the 1m window itself."""
import pandas as pd

from backend.strategy.gap_go import generate


def _two_days(day1_close: float, day2_closes: list[float]) -> pd.DataFrame:
    """Day 1: 30 flat 1m bars ending at day1_close. Day 2: 09:30 ET +."""
    i1 = pd.date_range("2026-06-08 15:30", periods=30, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    d1 = pd.DataFrame({"open": day1_close, "high": day1_close + 0.05,
                       "low": day1_close - 0.05, "close": day1_close,
                       "volume": 5_000.0}, index=i1)
    i2 = pd.date_range("2026-06-09 09:30", periods=len(day2_closes), freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series(day2_closes, index=i2)
    d2 = pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.05,
                       "low": c - 0.05, "close": c, "volume": 20_000.0})
    return pd.concat([d1, d2])


def test_gap_up_hold_above_vwap_break_5m_high_fires_buy():
    # prev close 100; opens 103 (3% gap); 5 bars 102.8..103.2; bar 6 breaks to 103.6
    df = _two_days(100.0, [103.0, 102.9, 103.0, 103.1, 103.2, 103.6])
    sig = generate(df, gap_min_pct=2.0, confirm_minutes=5)
    assert sig["buy"] is True
    assert sig["stop_loss_pct"] > 0          # stop at VWAP distance
    assert sig["time_stop_bars"] > 0


def test_no_gap_no_signal():
    df = _two_days(100.0, [100.4, 100.5, 100.6, 100.7, 100.8, 101.2])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_gap_fill_disqualifies():
    # gaps to 103 but trades back through prior close (100) -> dead gap, skip
    df = _two_days(100.0, [103.0, 101.0, 99.9, 103.0, 103.2, 103.6])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_below_vwap_disqualifies():
    # gap up then steady fade: last close below session VWAP
    df = _two_days(100.0, [103.0, 102.8, 102.5, 102.2, 102.0, 102.1])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_no_prior_session_no_signal():
    i2 = pd.date_range("2026-06-09 09:30", periods=6, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series([103.0, 102.9, 103.0, 103.1, 103.2, 103.6], index=i2)
    df = pd.DataFrame({"open": c, "high": c + 0.05, "low": c - 0.05,
                       "close": c, "volume": 1000.0})
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_gap_go.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.strategy.gap_go`.

- [ ] **Step 3: Implement `backend/strategy/gap_go.py`**

```python
"""Gap-and-Go — momentum continuation on large opening gaps.

Long setup: today's open gaps >= gap_min_pct above the prior session close, price
has NOT filled the gap (never traded back through the prior close), the last bar
holds above session VWAP and is the FIRST close above the opening
`confirm_minutes` high. Stop at VWAP, ~2R target, hard exit 15:55 ET via
per-signal overrides. Mirrored short side behind allow_short (default off).

Prior session close comes from the 1m window itself (last bar of the most recent
earlier session) — works identically live and in backtest.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import vwap

SESSION_TZ = "America/New_York"
OPEN = "09:30"
LAST_ENTRY = "15:30"
HARD_EXIT = "15:55"


def generate(
    df: pd.DataFrame,
    *,
    gap_min_pct: float = 2.0,
    confirm_minutes: int = 5,
    risk_reward: float = 2.0,
    allow_short: bool = False,
) -> dict:
    no = {"buy": False, "sell": False}
    if len(df) < confirm_minutes + 2:
        return no
    et = df.copy()
    et.index = et.index.tz_convert(SESSION_TZ)
    last_ts = et.index[-1]
    if last_ts.time() > pd.Timestamp(f"2000-01-01 {LAST_ENTRY}").time():
        return no
    today = et[et.index.date == last_ts.date()].between_time(OPEN, "16:00")
    prior = et[et.index.date < last_ts.date()]
    if prior.empty or len(today) < confirm_minutes + 1:
        return no
    prev_close = float(prior["close"].iloc[-1])
    open_print = float(today["open"].iloc[0])
    gap_pct = (open_print / prev_close - 1.0) * 100.0

    v = float(vwap(today).iloc[-1])
    close = float(today["close"].iloc[-1])
    prev_bar_close = float(today["close"].iloc[-2])
    hi_n = float(today["high"].iloc[:confirm_minutes].max())
    lo_n = float(today["low"].iloc[:confirm_minutes].min())

    buy = sell = False
    if gap_pct >= gap_min_pct:
        filled = bool((today["low"] <= prev_close).any())
        buy = (not filled) and close > v and prev_bar_close <= hi_n and close > hi_n
    elif allow_short and gap_pct <= -gap_min_pct:
        filled = bool((today["high"] >= prev_close).any())
        sell = (not filled) and close < v and prev_bar_close >= lo_n and close < lo_n
    if not (buy or sell):
        return no

    stop_pct = abs(close - v) / close * 100.0
    if stop_pct <= 0.01:                       # too close to VWAP — no edge to risk
        return no
    bars_to_exit = max(1, int((pd.Timestamp(f"{last_ts.date()} {HARD_EXIT}",
                                            tz=SESSION_TZ) - last_ts).total_seconds() // 60))
    return {
        "buy": buy, "sell": sell,
        "stop_loss_pct": round(stop_pct, 4),
        "take_profit_pct": round(risk_reward * stop_pct, 4),
        "time_stop_bars": bars_to_exit,
        "gap_pct": round(gap_pct, 3), "vwap": round(v, 4),
    }


class GapGoStrategy:
    name = "gap_go"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("gap_go", {})
        res = generate(
            ctx.window,
            gap_min_pct=p.get("gap_min_pct", 2.0),
            confirm_minutes=p.get("confirm_minutes", 5),
            risk_reward=p.get("risk_reward", 2.0),
            allow_short=p.get("allow_short", False),
        )
        side = "buy" if res.get("buy") else "sell" if res.get("sell") else None
        return StrategySignal(side=side, strength=abs(res.get("gap_pct", 0.0)) if side else 0.0,
                              meta=res)
```

- [ ] **Step 4: Register + config**

`backend/strategy/registry.py`: add `from .gap_go import GapGoStrategy` and map entry `"gap_go": GapGoStrategy,`.

`backend/config.yaml`, after the `orb_breakout:` block:

```yaml
gap_go:
  gap_min_pct: 2.0
  confirm_minutes: 5
  risk_reward: 2.0
  allow_short: false
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest backend/tests/test_gap_go.py backend/tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/strategy/gap_go.py backend/strategy/registry.py backend/config.yaml backend/tests/test_gap_go.py
git commit -m "feat(strategy): gap-and-go continuation"
```

---

### Task 6: Portfolio protocol + portfolio backtest engine

**Files:**
- Modify: `backend/strategy/base.py` (add `UniverseContext`, `PortfolioStrategy`)
- Create: `backend/backtest/portfolio_engine.py`
- Test: `backend/tests/test_portfolio_engine.py`

- [ ] **Step 1: Write the failing test**

```python
"""Portfolio engine: rank -> hold-top-N rebalancing on daily bars, no lookahead."""
import pandas as pd
import pytest

from backend.backtest.portfolio_engine import run_portfolio_backtest


def _frame(daily_rets: list[float], start="2024-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(daily_rets) + 1, tz="UTC")
    px = [100.0]
    for r in daily_rets:
        px.append(px[-1] * (1 + r))
    s = pd.Series(px, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": 1e6})


class AlwaysWinner:
    name = "always_winner"
    def rebalance(self, ctx):
        return {"WIN": 1.0}


class Peeker:
    """Asserts the engine never hands us bars after the rebalance date."""
    name = "peeker"
    def rebalance(self, ctx):
        for sym, df in ctx.frames.items():
            assert df.index.max() <= ctx.date, f"{sym} leaked future bars"
        return {"WIN": 1.0}


def _frames():
    n = 300
    return {"WIN": _frame([0.002] * n), "LOSE": _frame([-0.002] * n)}


def test_holding_the_winner_makes_money():
    res = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=0.0)
    assert res.error == ""
    assert res.total_return_pct > 20.0
    assert res.n_rebalances >= 10           # ~14 month-ends in 300 bdays
    assert res.max_drawdown_pct < 5.0
    assert len(res.equity_curve) > 200


def test_no_future_bars_reach_the_strategy():
    run_portfolio_backtest(_frames(), Peeker(), cost_bps=0.0)  # Peeker asserts


def test_turnover_costs_reduce_return():
    free = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=0.0)
    costly = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=50.0)
    assert costly.total_return_pct < free.total_return_pct


def test_all_cash_strategy_flat():
    class Cash:
        name = "cash"
        def rebalance(self, ctx):
            return {}
    res = run_portfolio_backtest(_frames(), Cash(), cost_bps=0.0)
    assert abs(res.total_return_pct) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_portfolio_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.backtest.portfolio_engine`.

- [ ] **Step 3: Add protocols to `backend/strategy/base.py`**

Append at the end of the file:

```python
@dataclass
class UniverseContext:
    """Cross-sectional view handed to a PortfolioStrategy at one rebalance date.

    frames hold DAILY bars per symbol, truncated to <= date (engine guarantees
    no future rows — same anti-lookahead contract as BarContext)."""

    date: pd.Timestamp
    frames: dict  # symbol -> daily OHLCV DataFrame, index <= date
    config: dict = field(default_factory=dict)


class PortfolioStrategy(Protocol):
    """Returns target weights {symbol: weight}; weights sum <= 1.0, remainder is
    cash. Empty dict = 100% cash. Never touches a broker."""

    name: str

    def rebalance(self, ctx: UniverseContext) -> dict: ...
```

- [ ] **Step 4: Implement `backend/backtest/portfolio_engine.py`**

```python
"""Portfolio backtest engine — rank -> hold-top-N with periodic rebalancing.

Anti-lookahead contract (mirrors engine.py):
  * The strategy sees frames truncated to <= the rebalance date.
  * New weights take effect from the NEXT trading day's return onward.
Costs: cost_bps charged on turnover sum(|w_new - w_old|) at each rebalance.
Weights are held constant between rebalances (daily-rebalanced-to-target
approximation — fine for monthly cadence, documented here on purpose).

Pure: frames + strategy in, PortfolioResult out. No network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class PortfolioResult:
    strategy: str = ""
    n_rebalances: int = 0
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe: float = 0.0               # annualized, from daily returns
    max_drawdown_pct: float = 0.0
    avg_turnover: float = 0.0         # mean sum|dw| per rebalance
    equity_curve: list = field(default_factory=list)   # [(iso_date, equity)]
    daily_returns: list = field(default_factory=list)
    yearly: dict = field(default_factory=dict)          # year -> return_pct
    error: str = ""


def run_portfolio_backtest(
    frames: dict,
    strategy,
    *,
    cost_bps: float = 5.0,
    rebalance_freq: str = "ME",       # pandas offset: month-end
    config: dict | None = None,
) -> PortfolioResult:
    from backend.strategy.base import UniverseContext

    config = config or {}
    if not frames:
        return PortfolioResult(strategy=getattr(strategy, "name", "?"), error="no data")

    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()
    closes = closes.dropna(how="all")
    if len(closes) < 60:
        return PortfolioResult(strategy=strategy.name, error="insufficient data")
    rets = closes.pct_change().fillna(0.0)

    # Rebalance on the last trading day of each period present in the data.
    period = "M" if rebalance_freq in ("M", "ME") else rebalance_freq
    marks = closes.groupby(closes.index.to_period(period)).tail(1).index
    rebal_dates = set(marks[:-1])     # last period end has no next day to trade

    weights: dict = {}
    equity = 1.0
    peak, max_dd = 1.0, 0.0
    curve, daily, turnovers = [], [], []
    n_rebal = 0

    dates = list(closes.index)
    for t, dt in enumerate(dates):
        # 1) earn today's return with weights decided strictly BEFORE today
        day_ret = sum(w * float(rets[s].iloc[t]) for s, w in weights.items() if s in rets.columns)
        equity *= (1.0 + day_ret)
        daily.append(day_ret)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((str(dt.date()), round(equity, 6)))

        # 2) if today is a rebalance mark, compute new weights from data <= today;
        #    they apply from tomorrow (loop order enforces this).
        if dt in rebal_dates:
            ctx = UniverseContext(
                date=dt,
                frames={s: f.loc[:dt] for s, f in frames.items()},
                config=config,
            )
            try:
                new_w = strategy.rebalance(ctx) or {}
            except Exception as exc:   # noqa: BLE001 — bubble as result error
                return PortfolioResult(strategy=strategy.name,
                                       error=f"rebalance raised: {exc}")
            turnover = sum(abs(new_w.get(s, 0.0) - weights.get(s, 0.0))
                           for s in set(new_w) | set(weights))
            equity *= (1.0 - turnover * cost_bps / 10_000.0)
            turnovers.append(turnover)
            weights = dict(new_w)
            n_rebal += 1

    total = (equity - 1.0) * 100.0
    years = max(len(dates) / 252.0, 1e-9)
    annual = ((equity ** (1 / years)) - 1.0) * 100.0 if equity > 0 else -100.0
    s = pd.Series(daily)
    sharpe = float(s.mean() / s.std() * (252 ** 0.5)) if s.std() > 0 else 0.0

    yearly: dict = {}
    eq = pd.Series([e for _, e in curve],
                   index=pd.to_datetime([d for d, _ in curve]))
    for year, grp in eq.groupby(eq.index.year):
        yearly[int(year)] = round((grp.iloc[-1] / grp.iloc[0] - 1.0) * 100.0, 2)

    return PortfolioResult(
        strategy=strategy.name, n_rebalances=n_rebal,
        total_return_pct=round(total, 3), annual_return_pct=round(annual, 3),
        sharpe=round(sharpe, 3), max_drawdown_pct=round(max_dd * 100.0, 3),
        avg_turnover=round(sum(turnovers) / len(turnovers), 4) if turnovers else 0.0,
        equity_curve=curve, daily_returns=daily, yearly=yearly,
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest backend/tests/test_portfolio_engine.py backend/tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/strategy/base.py backend/backtest/portfolio_engine.py backend/tests/test_portfolio_engine.py
git commit -m "feat(backtest): portfolio engine + PortfolioStrategy protocol"
```

---

### Task 7: Cross-sectional momentum + sector rotation

**Files:**
- Create: `backend/strategy/xs_momentum.py`
- Create: `backend/strategy/sector_rotation.py`
- Modify: `backend/strategy/registry.py` (new `PORTFOLIO_STRATEGIES` map)
- Modify: `backend/config.yaml`
- Test: `backend/tests/test_portfolio_strategies.py`

- [ ] **Step 1: Write the failing test**

```python
"""xs_momentum + sector_rotation rebalance logic on synthetic daily frames."""
import pandas as pd

from backend.strategy.base import UniverseContext
from backend.strategy.sector_rotation import SectorRotationStrategy
from backend.strategy.xs_momentum import XsMomentumStrategy


def _frame(total_ret: float, n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    r = (1 + total_ret) ** (1 / (n - 1)) - 1
    px = pd.Series([100.0 * (1 + r) ** i for i in range(n)], index=idx)
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 1e6})


def _ctx(frames, config):
    last = max(f.index.max() for f in frames.values())
    return UniverseContext(date=last, frames=frames, config=config)


def test_xs_momentum_picks_strongest_equal_weight():
    frames = {"HOT": _frame(0.9), "WARM": _frame(0.4), "COLD": _frame(-0.3),
              "SPY": _frame(0.2)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 2, "regime_filter": False}}))
    assert set(w) == {"HOT", "WARM"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["HOT"] - 0.5) < 1e-9


def test_xs_momentum_goes_cash_when_spy_below_200dma():
    # SPY trending down -> price below its 200-day MA -> all cash
    frames = {"HOT": _frame(0.9), "SPY": _frame(-0.4)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 1, "regime_filter": True}}))
    assert w == {}


def test_xs_momentum_skips_short_history_symbols():
    frames = {"HOT": _frame(0.9), "NEW": _frame(5.0, n=60), "SPY": _frame(0.2)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 1, "regime_filter": False}}))
    assert "NEW" not in w and "HOT" in w


def test_sector_rotation_top3_blended():
    frames = {f"X{i}": _frame(0.05 * i) for i in range(1, 12)}  # X11 strongest
    frames["SPY"] = _frame(0.2)
    s = SectorRotationStrategy()
    w = s.rebalance(_ctx(frames, {"sector_rotation": {
        "etfs": [f"X{i}" for i in range(1, 12)], "top_n": 3, "regime_filter": False}}))
    assert set(w) == {"X11", "X10", "X9"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_portfolio_strategies.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/strategy/xs_momentum.py`**

```python
"""Cross-sectional momentum — the most robust documented equity anomaly.

Monthly rebalance: rank the universe by 12-1 momentum (252-day return skipping
the most recent 21 days, to dodge short-term reversal), hold the top_n names
equal-weight. Regime filter: 100% cash while SPY < its 200-day MA.
"""
from __future__ import annotations

import pandas as pd

from .base import UniverseContext

LOOKBACK = 252
SKIP = 21
MIN_BARS = LOOKBACK + SKIP


def regime_ok(frames: dict, *, benchmark: str = "SPY", ma_days: int = 200) -> bool:
    """True when the benchmark closes above its ma_days moving average (or when
    the benchmark is missing — fail open so tests/universes without SPY work)."""
    bench = frames.get(benchmark)
    if bench is None or len(bench) < ma_days:
        return True
    close = bench["close"]
    return float(close.iloc[-1]) > float(close.rolling(ma_days).mean().iloc[-1])


def momentum_12_1(close: pd.Series) -> float:
    return float(close.iloc[-1 - SKIP] / close.iloc[-MIN_BARS] - 1.0)


class XsMomentumStrategy:
    name = "xs_momentum"

    def rebalance(self, ctx: UniverseContext) -> dict:
        p = ctx.config.get("xs_momentum", {})
        top_n = p.get("top_n", 20)
        benchmark = p.get("benchmark", "SPY")
        if p.get("regime_filter", True) and not regime_ok(ctx.frames, benchmark=benchmark):
            return {}
        scores = {}
        for sym, df in ctx.frames.items():
            if sym == benchmark or len(df) < MIN_BARS:
                continue
            scores[sym] = momentum_12_1(df["close"])
        winners = sorted(scores, key=scores.get, reverse=True)[:top_n]
        if not winners:
            return {}
        w = 1.0 / len(winners)
        return {s: w for s in winners}
```

- [ ] **Step 4: Implement `backend/strategy/sector_rotation.py`**

```python
"""Sector rotation over the 11 SPDR sector ETFs.

Monthly: rank ETFs by blended momentum (mean of 3-, 6-, 12-month returns), hold
the top_n equal-weight. Same SPY 200-day cash filter as xs_momentum.
"""
from __future__ import annotations

import pandas as pd

from .base import UniverseContext
from .xs_momentum import regime_ok

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
               "XLI", "XLB", "XLRE", "XLU", "XLC"]
WINDOWS = (63, 126, 252)             # ~3, 6, 12 months of trading days


def blended_momentum(close: pd.Series) -> float:
    return float(sum(close.iloc[-1] / close.iloc[-w] - 1.0 for w in WINDOWS) / len(WINDOWS))


class SectorRotationStrategy:
    name = "sector_rotation"

    def rebalance(self, ctx: UniverseContext) -> dict:
        p = ctx.config.get("sector_rotation", {})
        etfs = p.get("etfs", SECTOR_ETFS)
        top_n = p.get("top_n", 3)
        if p.get("regime_filter", True) and not regime_ok(
                ctx.frames, benchmark=p.get("benchmark", "SPY")):
            return {}
        scores = {}
        for sym in etfs:
            df = ctx.frames.get(sym)
            if df is None or len(df) < max(WINDOWS) + 1:
                continue
            scores[sym] = blended_momentum(df["close"])
        winners = sorted(scores, key=scores.get, reverse=True)[:top_n]
        if not winners:
            return {}
        w = 1.0 / len(winners)
        return {s: w for s in winners}
```

- [ ] **Step 5: Register + config**

In `backend/strategy/registry.py` add imports and a third map (after `CONFIRMATION_STRATEGIES`):

```python
from .sector_rotation import SectorRotationStrategy
from .xs_momentum import XsMomentumStrategy
```

```python
PORTFOLIO_STRATEGIES: dict[str, type] = {
    "xs_momentum": XsMomentumStrategy,
    "sector_rotation": SectorRotationStrategy,
}
```

In `backend/config.yaml` after `gap_go:`:

```yaml
# Daily-bar portfolio strategies (tournament candidates)
xs_momentum:
  top_n: 20
  regime_filter: true
  benchmark: SPY
sector_rotation:
  top_n: 3
  regime_filter: true
  benchmark: SPY
```

- [ ] **Step 6: Run tests, commit**

Run: `.venv/bin/python -m pytest backend/tests/test_portfolio_strategies.py backend/tests/ -q`
Expected: PASS.

```bash
git add backend/strategy/xs_momentum.py backend/strategy/sector_rotation.py backend/strategy/registry.py backend/config.yaml backend/tests/test_portfolio_strategies.py
git commit -m "feat(strategy): cross-sectional momentum + sector rotation"
```

---

### Task 8: Earnings drift (PEAD)

**Files:**
- Create: `backend/strategy/earnings_drift.py`
- Modify: `backend/strategy/registry.py`, `backend/config.yaml`
- Test: `backend/tests/test_earnings_drift.py`

- [ ] **Step 1: Write the failing test**

```python
"""PEAD: big positive earnings gap + volume -> ride the drift ~20 days."""
import pandas as pd

from backend.strategy.earnings_drift import generate


def _daily(n: int = 60, gap_at: int | None = None, gap_pct: float = 8.0,
           vol_mult_on_gap: float = 3.0) -> pd.DataFrame:
    idx = pd.bdate_range("2026-03-02", periods=n, tz="UTC")
    close, open_, vol = [], [], []
    px = 100.0
    for i in range(n):
        o = px
        if gap_at is not None and i == gap_at:
            o = px * (1 + gap_pct / 100.0)
        px = o
        open_.append(o); close.append(px)
        vol.append(1e6 * (vol_mult_on_gap if i == gap_at else 1.0))
    return pd.DataFrame({"open": open_, "high": [c * 1.01 for c in close],
                         "low": [c * 0.99 for c in close], "close": close,
                         "volume": vol}, index=idx)


def test_earnings_gap_up_fires_buy_with_hold_exits():
    df = _daily(n=40, gap_at=39)
    earn = [df.index[39].tz_localize(None).normalize()]
    sig = generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                   hold_days=20, stop_pct=10.0)
    assert sig["buy"] is True
    assert sig["time_stop_bars"] == 20
    assert sig["stop_loss_pct"] == 10.0


def test_gap_without_earnings_date_no_signal():
    df = _daily(n=40, gap_at=39)
    assert generate(df, earnings_dates=[], gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False


def test_small_gap_no_signal():
    df = _daily(n=40, gap_at=39, gap_pct=2.0)
    earn = [df.index[39].tz_localize(None).normalize()]
    assert generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False


def test_low_volume_gap_no_signal():
    df = _daily(n=40, gap_at=39, vol_mult_on_gap=1.0)
    earn = [df.index[39].tz_localize(None).normalize()]
    assert generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False
```

- [ ] **Step 2: Run to verify FAIL** — `.venv/bin/python -m pytest backend/tests/test_earnings_drift.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/strategy/earnings_drift.py`**

```python
"""Post-Earnings-Announcement Drift (PEAD) on daily bars.

If the LAST bar is an earnings reaction day (its date within match_days of a
known earnings date) AND it gapped >= gap_min_pct over the prior close AND
volume >= vol_mult x its 20-day average, go long; hold `hold_days` with a
stop_pct stop and no profit target (per-signal overrides, take_profit huge).
Short side (negative surprise) behind allow_short, default off.

generate() is pure: earnings_dates are passed in. EarningsDriftStrategy wires
the EarningsCalendar at the tournament layer (it needs daily bars, so it is a
tournament/swing strategy, not a live 1m runner strategy).
"""
from __future__ import annotations

import pandas as pd

VOL_AVG_DAYS = 20
NO_TP = 1000.0   # effectively "no take-profit" via the per-signal override


def generate(
    df: pd.DataFrame,
    *,
    earnings_dates: list,
    gap_min_pct: float = 5.0,
    vol_mult: float = 1.5,
    hold_days: int = 20,
    stop_pct: float = 10.0,
    match_days: int = 1,
    allow_short: bool = False,
) -> dict:
    no = {"buy": False, "sell": False}
    if len(df) < VOL_AVG_DAYS + 2 or not earnings_dates:
        return no
    last = df.index[-1]
    last_day = pd.Timestamp(last.date())
    if not any(abs((last_day - pd.Timestamp(e).normalize()).days) <= match_days
               for e in earnings_dates):
        return no
    prev_close = float(df["close"].iloc[-2])
    open_ = float(df["open"].iloc[-1])
    gap_pct = (open_ / prev_close - 1.0) * 100.0
    avg_vol = float(df["volume"].iloc[-VOL_AVG_DAYS - 1:-1].mean())
    vol_ok = avg_vol > 0 and float(df["volume"].iloc[-1]) >= vol_mult * avg_vol

    buy = vol_ok and gap_pct >= gap_min_pct
    sell = allow_short and vol_ok and gap_pct <= -gap_min_pct
    if not (buy or sell):
        return no
    return {"buy": bool(buy), "sell": bool(sell),
            "stop_loss_pct": stop_pct, "take_profit_pct": NO_TP,
            "time_stop_bars": hold_days, "gap_pct": round(gap_pct, 3)}
```

- [ ] **Step 4: Config (registry: PEAD is daily-bar only — used by the tournament directly, not the 1m runner, so no SIGNAL_STRATEGIES entry)**

`backend/config.yaml` after `sector_rotation:`:

```yaml
earnings_drift:
  gap_min_pct: 5.0
  vol_mult: 1.5
  hold_days: 20
  stop_pct: 10.0
  allow_short: false
```

- [ ] **Step 5: Run tests, commit**

Run: `.venv/bin/python -m pytest backend/tests/test_earnings_drift.py backend/tests/ -q` → PASS.

```bash
git add backend/strategy/earnings_drift.py backend/config.yaml backend/tests/test_earnings_drift.py
git commit -m "feat(strategy): post-earnings-announcement drift (PEAD)"
```

---

### Task 9: Pairs engine + pairs stat-arb

**Files:**
- Modify: `requirements.txt` (add `statsmodels>=0.14`)
- Create: `backend/backtest/pairs_engine.py`
- Create: `backend/strategy/pairs_statarb.py`
- Modify: `backend/config.yaml`
- Test: `backend/tests/test_pairs.py`

- [ ] **Step 1: Add dependency**

In `requirements.txt`, after `requests>=2.31` add:

```
statsmodels>=0.14   # pairs stat-arb: Engle-Granger cointegration test
```

Run: `.venv/bin/pip install "statsmodels>=0.14"`

- [ ] **Step 2: Write the failing test**

```python
"""Pairs: cointegration selection + spread z-score backtest on synthetic data."""
import numpy as np
import pandas as pd

from backend.backtest.pairs_engine import find_pairs, run_pairs_backtest


def _coint_pair(n: int = 600, seed: int = 7):
    rng = np.random.default_rng(seed)
    a = 100 + np.cumsum(rng.normal(0, 0.5, n))
    spread = np.zeros(n)
    for i in range(1, n):                       # strongly mean-reverting spread
        spread[i] = 0.8 * spread[i - 1] + rng.normal(0, 0.4)
    b = a + spread
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    f = lambda px: pd.DataFrame({"open": px, "high": px, "low": px,
                                 "close": px, "volume": 1e6}, index=idx)
    return f(a), f(b)


def _random_pair(n: int = 600, seed: int = 11):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    f = lambda px: pd.DataFrame({"open": px, "high": px, "low": px,
                                 "close": px, "volume": 1e6}, index=idx)
    return (f(100 + np.cumsum(rng.normal(0, 0.5, n))),
            f(100 + np.cumsum(rng.normal(0, 0.5, n))))


def test_find_pairs_detects_cointegration_and_rejects_random():
    ca, cb = _coint_pair()
    ra, rb = _random_pair()
    frames = {"KO": ca, "PEP": cb, "RND1": ra, "RND2": rb}
    pairs = find_pairs(frames, corr_min=0.5, pval_max=0.05, top_n=5)
    keys = {(p.sym_a, p.sym_b) for p in pairs}
    assert ("KO", "PEP") in keys or ("PEP", "KO") in keys
    assert all({"RND1", "RND2"} != {p.sym_a, p.sym_b} for p in pairs)


def test_pairs_backtest_trades_and_profits_on_mean_reverting_spread():
    ca, cb = _coint_pair()
    res = run_pairs_backtest(ca, cb, z_entry=2.0, z_exit=0.0, z_stop=3.5,
                             max_days=30, hedge_window=60, cost_bps=0.0)
    assert res["n_trades"] >= 5
    assert res["total_return_pct"] > 0          # mean reversion is real here
    assert all("ret_pct" in t for t in res["trades"])


def test_pairs_backtest_costs_reduce_return():
    ca, cb = _coint_pair()
    free = run_pairs_backtest(ca, cb, cost_bps=0.0)
    costly = run_pairs_backtest(ca, cb, cost_bps=20.0)
    assert costly["total_return_pct"] < free["total_return_pct"]
```

- [ ] **Step 3: Run to verify FAIL** — `.venv/bin/python -m pytest backend/tests/test_pairs.py -q` → `ModuleNotFoundError`.

- [ ] **Step 4: Implement `backend/backtest/pairs_engine.py`**

```python
"""Pairs stat-arb engine: cointegration selection + spread z-score backtest.

Selection: candidate pairs by close-price correlation, then Engle-Granger
cointegration (statsmodels coint); keep the strongest by p-value, annotated with
the spread's AR(1) mean-reversion half-life.

Backtest (daily): rolling OLS hedge ratio over hedge_window; spread z-score over
the same window. Enter long-spread at z <= -z_entry (buy A, sell B*beta), short-
spread at z >= +z_entry; exit at z crossing z_exit; stop at |z| >= z_stop or
max_days. Both legs dollar-neutral; cost_bps charged per leg per side.
Anti-lookahead: signals use data through day t; fills at day t+1's open.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PairSpec:
    sym_a: str
    sym_b: str
    pvalue: float
    half_life: float


def _half_life(spread: pd.Series) -> float:
    s = spread.dropna()
    lag, diff = s.shift(1).iloc[1:], s.diff().iloc[1:]
    beta = np.polyfit(lag, diff, 1)[0]
    if beta >= 0:
        return float("inf")
    return float(-np.log(2) / beta)


def find_pairs(frames: dict, *, corr_min: float = 0.8, pval_max: float = 0.05,
               top_n: int = 10) -> list[PairSpec]:
    from statsmodels.tsa.stattools import coint

    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).dropna()
    syms = list(closes.columns)
    corr = closes.corr()
    out: list[PairSpec] = []
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            if corr.loc[a, b] < corr_min:
                continue
            _, pval, _ = coint(closes[a], closes[b])
            if pval >= pval_max:
                continue
            beta = float(np.polyfit(closes[b], closes[a], 1)[0])
            out.append(PairSpec(a, b, float(pval),
                                _half_life(closes[a] - beta * closes[b])))
    out.sort(key=lambda p: p.pvalue)
    return out[:top_n]


def run_pairs_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame, *,
                       z_entry: float = 2.0, z_exit: float = 0.0,
                       z_stop: float = 3.5, max_days: int = 30,
                       hedge_window: int = 60, cost_bps: float = 3.0) -> dict:
    a, b = df_a["close"].align(df_b["close"], join="inner")
    oa, ob = df_a["open"].reindex(a.index), df_b["open"].reindex(b.index)
    n = len(a)
    if n < hedge_window + 10:
        return {"n_trades": 0, "total_return_pct": 0.0, "trades": [],
                "error": "insufficient data"}

    cost = cost_bps / 10_000.0
    equity, curve = 1.0, [1.0]
    trades: list[dict] = []
    pos = None   # dict(side, i0, pa, pb, beta)

    for t in range(hedge_window, n - 1):
        wa, wb = a.iloc[t - hedge_window:t + 1], b.iloc[t - hedge_window:t + 1]
        beta = float(np.polyfit(wb, wa, 1)[0])
        spread = wa - beta * wb
        mu, sd = float(spread.mean()), float(spread.std())
        if sd == 0:
            continue
        z = (float(spread.iloc[-1]) - mu) / sd

        if pos is not None:
            held = t - pos["i0"]
            crossed = (pos["side"] == "long" and z >= z_exit) or \
                      (pos["side"] == "short" and z <= z_exit)
            stopped = abs(z) >= z_stop or held >= max_days
            if crossed or stopped:
                # exit fills at NEXT open
                xa, xb = float(oa.iloc[t + 1]), float(ob.iloc[t + 1])
                sgn = 1.0 if pos["side"] == "long" else -1.0
                ret_a = sgn * (xa / pos["pa"] - 1.0)
                ret_b = -sgn * pos["beta_w"] * (xb / pos["pb"] - 1.0)
                ret = (ret_a + ret_b) / (1.0 + pos["beta_w"]) - 4 * cost
                equity *= (1.0 + ret)
                curve.append(equity)
                trades.append({"side": pos["side"], "entry_idx": pos["i0"],
                               "exit_idx": t + 1, "bars_held": held,
                               "reason": "z_exit" if crossed else
                                         ("z_stop" if abs(z) >= z_stop else "time_stop"),
                               "ret_pct": ret * 100.0})
                pos = None
                continue

        if pos is None and abs(z) >= z_entry:
            pa, pb = float(oa.iloc[t + 1]), float(ob.iloc[t + 1])  # next-open fill
            # dollar-neutral leg weights: 1 unit A vs beta-adjusted notional B
            beta_w = abs(beta) * pb / pa if pa > 0 else 1.0
            pos = {"side": "long" if z <= -z_entry else "short",
                   "i0": t + 1, "pa": pa, "pb": pb, "beta_w": beta_w}

    peak, max_dd = 1.0, 0.0
    for e in curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    return {"n_trades": len(trades), "total_return_pct": (equity - 1.0) * 100.0,
            "max_drawdown_pct": max_dd * 100.0, "trades": trades, "error": ""}
```

- [ ] **Step 5: Implement `backend/strategy/pairs_statarb.py`**

```python
"""Pairs stat-arb orchestrator for the tournament.

Honest split: pairs are SELECTED on the first train_frac of history only, then
TRADED on the remaining test slice — selection never sees test data. Aggregates
trades across the chosen pairs.
"""
from __future__ import annotations

import pandas as pd

from backend.backtest.pairs_engine import find_pairs, run_pairs_backtest


def run_pairs_strategy(frames: dict, *, train_frac: float = 0.6,
                       corr_min: float = 0.8, pval_max: float = 0.05,
                       top_n: int = 10, z_entry: float = 2.0, z_exit: float = 0.0,
                       z_stop: float = 3.5, max_days: int = 30,
                       hedge_window: int = 60, cost_bps: float = 3.0) -> dict:
    if not frames:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": "no data"}
    n = min(len(f) for f in frames.values())
    cut = int(n * train_frac)
    if cut < hedge_window + 30 or n - cut < hedge_window + 10:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": "insufficient data"}

    train = {s: f.iloc[:cut] for s, f in frames.items()}
    pairs = find_pairs(train, corr_min=corr_min, pval_max=pval_max, top_n=top_n)
    if not pairs:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": ""}

    all_trades, total_ret = [], 0.0
    for p in pairs:
        test_a = frames[p.sym_a].iloc[cut - hedge_window:]   # warm hedge window
        test_b = frames[p.sym_b].iloc[cut - hedge_window:]
        res = run_pairs_backtest(test_a, test_b, z_entry=z_entry, z_exit=z_exit,
                                 z_stop=z_stop, max_days=max_days,
                                 hedge_window=hedge_window, cost_bps=cost_bps)
        for t in res["trades"]:
            t["pair"] = f"{p.sym_a}/{p.sym_b}"
        all_trades.extend(res["trades"])
        total_ret += res["total_return_pct"] / len(pairs)   # equal capital per pair
    return {"n_trades": len(all_trades), "trades": all_trades,
            "total_return_pct": total_ret,
            "pairs": [f"{p.sym_a}/{p.sym_b}" for p in pairs], "error": ""}
```

- [ ] **Step 6: Config**

`backend/config.yaml` after `earnings_drift:`:

```yaml
pairs_statarb:
  train_frac: 0.6
  corr_min: 0.8
  pval_max: 0.05
  top_n: 10
  z_entry: 2.0
  z_exit: 0.0
  z_stop: 3.5
  max_days: 30
  hedge_window: 60
```

- [ ] **Step 7: Run tests, commit**

Run: `.venv/bin/python -m pytest backend/tests/test_pairs.py backend/tests/ -q` → PASS.

```bash
git add requirements.txt backend/backtest/pairs_engine.py backend/strategy/pairs_statarb.py backend/config.yaml backend/tests/test_pairs.py
git commit -m "feat(strategy): cointegrated pairs stat-arb + pairs engine"
```

---

### Task 10: Tournament orchestrator

**Files:**
- Create: `backend/backtest/tournament.py`
- Test: `backend/tests/test_tournament.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tournament: gates, ranking, error isolation, persistence."""
import json

import pandas as pd
import pytest

from backend.backtest.tournament import (
    GATES, StrategyReport, apply_gates, rank_reports, run_tournament, save_run,
    load_latest, list_runs,
)


def _report(name, *, sharpe=1.0, max_dd=10.0, pf=2.0, trades=200,
            kind="trades", significant=True, error=""):
    return StrategyReport(
        name=name, kind=kind, error=error,
        metrics={"oos_sharpe": sharpe, "max_drawdown_pct": max_dd,
                 "profit_factor": pf, "n_trades": trades,
                 "n_rebalances": trades, "significant": significant,
                 "total_return_pct": 10.0},
    )


def test_gates_pass_and_fail_reasons():
    ok = apply_gates(_report("good"))
    assert ok.passed and ok.failures == []
    bad = apply_gates(_report("dd", max_dd=35.0, pf=1.1, trades=5))
    assert not bad.passed
    assert any("drawdown" in f for f in bad.failures)
    assert any("profit factor" in f for f in bad.failures)
    assert any("trades" in f for f in bad.failures)


def test_portfolio_kind_uses_rebalance_gate():
    r = _report("port", kind="portfolio", trades=30)
    r.metrics["n_trades"] = 0
    r.metrics["n_rebalances"] = 30
    assert apply_gates(r).passed


def test_rank_orders_by_sharpe_passers_first():
    reports = [_report("a", sharpe=0.5), _report("b", sharpe=2.0),
               _report("c", max_dd=50.0), _report("err", error="boom")]
    ranked = rank_reports(reports)
    names = [r.name for r in ranked]
    assert names[:2] == ["b", "a"]          # passers by sharpe desc
    assert set(names[2:]) == {"c", "err"}   # failures after, never hidden


def test_run_tournament_isolates_strategy_errors():
    def good(config):
        return _report("good")

    def boom(config):
        raise RuntimeError("data exploded")

    run = run_tournament({}, runners={"good": good, "boom": boom})
    by_name = {r.name: r for r in run.reports}
    assert by_name["good"].error == ""
    assert "data exploded" in by_name["boom"].error
    assert run.ranked[0].name == "good"


def test_save_and_load_roundtrip(tmp_path):
    run = run_tournament({}, runners={"good": lambda c: _report("good")})
    path = save_run(run, store_dir=tmp_path)
    assert path.exists()
    latest = load_latest(store_dir=tmp_path)
    assert latest["reports"][0]["name"] == "good"
    assert list_runs(store_dir=tmp_path)[0]["file"] == path.name
```

- [ ] **Step 2: Run to verify FAIL** — `.venv/bin/python -m pytest backend/tests/test_tournament.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/backtest/tournament.py`**

```python
"""Strategy tournament — run every candidate, gate hard, rank honestly.

Gates (spec): max drawdown <= 20%, profit factor >= 1.3, >= 100 trades
(portfolio strategies: >= 24 rebalances), statistical significance. Gate-failers
stay on the leaderboard with the failed gate named — no survivorship hiding.
Ranking: passers by out-of-sample Sharpe, descending; then failers; errors last.

`runners` maps name -> callable(config) -> StrategyReport. The default runners
wire real data (DailyBarCache, EarningsCalendar, 1m provider history); tests
inject fakes. Every runner is exception-isolated: a crash becomes an error row,
never a dead tournament (spec: Error Handling).

Results persist as JSON under backend/store/tournament/.
"""
from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "store" / "tournament"

GATES = {
    "max_drawdown_pct": 20.0,
    "profit_factor": 1.3,
    "min_trades": 100,
    "min_rebalances": 24,
}


@dataclass
class GateResult:
    passed: bool = True
    failures: list = field(default_factory=list)


@dataclass
class StrategyReport:
    name: str
    kind: str = "trades"             # "trades" | "portfolio" | "pairs"
    metrics: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)
    windows: list = field(default_factory=list)   # per-year / per-fold detail
    gates: Optional[dict] = None
    error: str = ""


@dataclass
class TournamentRun:
    started_at: str = ""
    config_hash: str = ""
    reports: list = field(default_factory=list)
    ranked: list = field(default_factory=list)


def apply_gates(report: StrategyReport) -> GateResult:
    if report.error:
        return GateResult(passed=False, failures=[f"error: {report.error}"])
    m = report.metrics
    out = GateResult()
    if m.get("max_drawdown_pct", 1e9) > GATES["max_drawdown_pct"]:
        out.failures.append(
            f"max drawdown {m.get('max_drawdown_pct'):.1f}% > {GATES['max_drawdown_pct']}%")
    if m.get("profit_factor", 0.0) < GATES["profit_factor"]:
        out.failures.append(
            f"profit factor {m.get('profit_factor'):.2f} < {GATES['profit_factor']}")
    if report.kind == "portfolio":
        if m.get("n_rebalances", 0) < GATES["min_rebalances"]:
            out.failures.append(
                f"rebalances {m.get('n_rebalances', 0)} < {GATES['min_rebalances']}")
    else:
        if m.get("n_trades", 0) < GATES["min_trades"]:
            out.failures.append(
                f"trades {m.get('n_trades', 0)} < {GATES['min_trades']}")
    if not m.get("significant", False):
        out.failures.append("returns not statistically significant")
    out.passed = not out.failures
    return out


def rank_reports(reports: list) -> list:
    for r in reports:
        r.gates = asdict(apply_gates(r))
    passers = [r for r in reports if r.gates["passed"]]
    failers = [r for r in reports if not r.gates["passed"] and not r.error]
    errors = [r for r in reports if r.error]
    key = lambda r: r.metrics.get("oos_sharpe", -1e9)
    return sorted(passers, key=key, reverse=True) + \
        sorted(failers, key=key, reverse=True) + errors


def run_tournament(config: dict, *, runners: Optional[dict] = None,
                   progress: Optional[Callable[[str, int, int], None]] = None) -> TournamentRun:
    runners = runners if runners is not None else default_runners(config)
    reports: list[StrategyReport] = []
    total = len(runners)
    for i, (name, fn) in enumerate(runners.items(), 1):
        if progress:
            progress(name, i, total)
        try:
            reports.append(fn(config))
        except Exception as exc:     # noqa: BLE001 — spec: never kill the run
            reports.append(StrategyReport(name=name, error=str(exc)))
    run = TournamentRun(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        config_hash=hashlib.sha256(
            json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:12],
        reports=reports,
    )
    run.ranked = rank_reports(reports)
    return run


# ---------------------------------------------------------------- persistence

def save_run(run: TournamentRun, *, store_dir: Path | str = DEFAULT_STORE) -> Path:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": run.started_at, "config_hash": run.config_hash,
        "reports": [asdict(r) for r in run.ranked],
    }
    name = f"run_{run.started_at.replace(':', '').replace('-', '')}.json"
    path = store / name
    path.write_text(json.dumps(payload, indent=1, default=str))
    return path


def list_runs(*, store_dir: Path | str = DEFAULT_STORE) -> list[dict]:
    store = Path(store_dir)
    if not store.exists():
        return []
    out = []
    for p in sorted(store.glob("run_*.json"), reverse=True):
        data = json.loads(p.read_text())
        out.append({"file": p.name, "started_at": data.get("started_at"),
                    "n_strategies": len(data.get("reports", []))})
    return out


def load_latest(*, store_dir: Path | str = DEFAULT_STORE) -> Optional[dict]:
    store = Path(store_dir)
    files = sorted(store.glob("run_*.json"), reverse=True) if store.exists() else []
    return json.loads(files[0].read_text()) if files else None


# ------------------------------------------------------------ default runners

def _trade_metrics(trades_pct: list[float], equity_curve: list[float]) -> dict:
    """Shared metric block from per-trade % returns (engine-style strategies)."""
    from .stats import significance

    if not trades_pct:
        return {"oos_sharpe": 0.0, "n_trades": 0, "profit_factor": 0.0,
                "max_drawdown_pct": 0.0, "total_return_pct": 0.0,
                "significant": False}
    wins = sum(r for r in trades_pct if r > 0)
    losses = -sum(r for r in trades_pct if r < 0)
    pf = wins / losses if losses > 0 else 999.0
    mean = sum(trades_pct) / len(trades_pct)
    var = sum((r - mean) ** 2 for r in trades_pct) / len(trades_pct)
    sharpe = mean / (var ** 0.5) if var > 0 else 0.0
    peak, max_dd, eq = 1.0, 0.0, 1.0
    curve = equity_curve or []
    if not curve:
        for r in trades_pct:
            eq *= (1 + r / 100.0)
            curve.append(eq)
    for e in curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    sg = significance(trades_pct)
    return {"oos_sharpe": round(sharpe, 3), "n_trades": len(trades_pct),
            "profit_factor": round(min(pf, 999.0), 3),
            "max_drawdown_pct": round(max_dd * 100.0, 3),
            "total_return_pct": round((curve[-1] - 1.0) * 100.0, 3) if curve else 0.0,
            "significant": bool(sg.significant), "p_value": sg.p_value}


def default_runners(config: dict) -> dict:
    """Wire real data sources. Heavy imports stay inside so tests never pay them."""
    from backend.data.daily_cache import DailyBarCache
    from backend.data.earnings import EarningsCalendar, EarningsUnavailable
    from backend.universe import load_universe

    tcfg = config.get("tournament", {})
    store = Path(__file__).resolve().parent.parent / "store"
    cache = DailyBarCache(store / "daily_cache")
    universe = load_universe(config)
    daily_symbols = tcfg.get("daily_symbols") or universe
    intraday_symbols = tcfg.get("intraday_symbols") or universe[:20]
    lookback_1m = int(tcfg.get("intraday_lookback_bars", 30 * 390))
    cost_bps = float(tcfg.get("cost_bps", 5.0))

    def _provider():
        from backend.brokers import build_data_provider  # follows existing wiring
        return build_data_provider(config)

    def _daily_frames(symbols, extra=()):
        rep = cache.ensure(list(dict.fromkeys([*symbols, *extra])), min_years=3)
        return {s: cache.get(s) for s in rep.included}, rep

    def run_intraday(name, generate, params):
        def runner(cfg):
            provider = _provider()
            all_trades, n_sym = [], 0
            from .engine import CostModel, ExitParams, run_backtest
            for sym in intraday_symbols:
                df = provider.get_recent_bars(sym, "1m", lookback_1m)
                if df is None or len(df) < 500:
                    continue
                n_sym += 1
                res = run_backtest(
                    df, lambda w: generate(w, **params),
                    exits=ExitParams(take_profit_pct=2.0, stop_loss_pct=1.0,
                                     allow_short=True),
                    costs=CostModel(1.0, 2.0), warmup=60, scenario=f"{name}:{sym}")
                all_trades.extend(t.ret_pct for t in res.trades)
            rep = StrategyReport(name=name, kind="trades",
                                 metrics=_trade_metrics(all_trades, []))
            rep.metrics["symbols_tested"] = n_sym
            return rep
        return runner

    def run_portfolio(name, strategy_cls):
        def runner(cfg):
            frames, rep = _daily_frames(daily_symbols, extra=["SPY"])
            from .portfolio_engine import run_portfolio_backtest
            res = run_portfolio_backtest(frames, strategy_cls(), cost_bps=cost_bps,
                                         config=cfg)
            if res.error:
                return StrategyReport(name=name, kind="portfolio", error=res.error)
            from .stats import significance
            sg = significance([r * 100.0 for r in res.daily_returns if r != 0.0])
            return StrategyReport(
                name=name, kind="portfolio",
                metrics={"oos_sharpe": res.sharpe,
                         "max_drawdown_pct": res.max_drawdown_pct,
                         "profit_factor": _pf_from_daily(res.daily_returns),
                         "n_rebalances": res.n_rebalances,
                         "total_return_pct": res.total_return_pct,
                         "annual_return_pct": res.annual_return_pct,
                         "significant": bool(sg.significant),
                         "excluded_symbols": rep.excluded},
                equity_curve=res.equity_curve[::5],     # downsample for JSON
                windows=[{"year": y, "return_pct": r} for y, r in res.yearly.items()],
            )
        return runner

    def run_earnings(cfg):
        from .engine import CostModel, ExitParams, run_backtest
        from backend.strategy.earnings_drift import generate as gen
        cal = EarningsCalendar(store / "earnings_cache")
        params = cfg.get("earnings_drift", {})
        frames, rep = _daily_frames(daily_symbols)
        all_trades = []
        unavailable = 0
        for sym, df in frames.items():
            try:
                dates = cal.get_dates(sym)
            except EarningsUnavailable:
                unavailable += 1
                continue
            res = run_backtest(
                df, lambda w: gen(w, earnings_dates=dates,
                                  gap_min_pct=params.get("gap_min_pct", 5.0),
                                  vol_mult=params.get("vol_mult", 1.5),
                                  hold_days=params.get("hold_days", 20),
                                  stop_pct=params.get("stop_pct", 10.0)),
                exits=ExitParams(take_profit_pct=1000.0, stop_loss_pct=10.0,
                                 allow_short=False),
                costs=CostModel(1.0, 2.0), warmup=25, scenario=f"pead:{sym}")
            all_trades.extend(t.ret_pct for t in res.trades)
        if unavailable == len(frames):
            return StrategyReport(name="earnings_drift", kind="trades",
                                  error="earnings data unavailable")
        r = StrategyReport(name="earnings_drift", kind="trades",
                           metrics=_trade_metrics(all_trades, []))
        r.metrics["earnings_unavailable_symbols"] = unavailable
        return r

    def run_pairs(cfg):
        from backend.strategy.pairs_statarb import run_pairs_strategy
        p = cfg.get("pairs_statarb", {})
        frames, rep = _daily_frames(daily_symbols)
        res = run_pairs_strategy(frames, **{k: v for k, v in p.items()
                                            if k in ("train_frac", "corr_min",
                                                     "pval_max", "top_n", "z_entry",
                                                     "z_exit", "z_stop", "max_days",
                                                     "hedge_window")})
        if res["error"]:
            return StrategyReport(name="pairs_statarb", kind="pairs", error=res["error"])
        r = StrategyReport(name="pairs_statarb", kind="pairs",
                           metrics=_trade_metrics([t["ret_pct"] for t in res["trades"]], []))
        r.metrics["pairs"] = res["pairs"]
        return r

    from backend.strategy.orb_breakout import generate as orb_gen
    from backend.strategy.gap_go import generate as gap_gen
    from backend.strategy.sector_rotation import SectorRotationStrategy
    from backend.strategy.xs_momentum import XsMomentumStrategy

    orb_p = {k: v for k, v in config.get("orb_breakout", {}).items()}
    gap_p = {k: v for k, v in config.get("gap_go", {}).items()}
    return {
        "orb_breakout": run_intraday("orb_breakout", orb_gen, orb_p),
        "gap_go": run_intraday("gap_go", gap_gen, gap_p),
        "xs_momentum": run_portfolio("xs_momentum", XsMomentumStrategy),
        "sector_rotation": run_portfolio("sector_rotation", SectorRotationStrategy),
        "earnings_drift": run_earnings,
        "pairs_statarb": run_pairs,
    }


def _pf_from_daily(daily: list[float]) -> float:
    wins = sum(r for r in daily if r > 0)
    losses = -sum(r for r in daily if r < 0)
    return round(wins / losses, 3) if losses > 0 else 999.0
```

**Note for the implementer:** `default_runners` references `backend.brokers.build_data_provider`. Open `backend/brokers.py` first and use whatever factory it actually exposes for the equity `DataProvider` (the runner module already constructs one — mirror that call). If the factory has a different name, adapt the one line in `_provider()`; everything else is provider-agnostic. This is the only intentionally codebase-adaptive line in the plan.

- [ ] **Step 4: Run tests, commit**

Run: `.venv/bin/python -m pytest backend/tests/test_tournament.py backend/tests/ -q` → PASS (tests use injected runners; `default_runners` is not exercised by unit tests).

```bash
git add backend/backtest/tournament.py backend/tests/test_tournament.py
git commit -m "feat(backtest): strategy tournament with gates + honest ranking"
```

---

### Task 11: Tournament API endpoints

**Files:**
- Modify: `backend/web/app.py`
- Test: `backend/tests/test_tournament_api.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tournament API: run (background), latest, runs list."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import backend.web.app as webapp
    monkeypatch.setattr(webapp, "TOURNAMENT_STORE", tmp_path)

    from backend.backtest.tournament import StrategyReport, TournamentRun, rank_reports

    def fake_run_tournament(config, runners=None, progress=None):
        rep = StrategyReport(name="fake", kind="trades",
                             metrics={"oos_sharpe": 1.0, "max_drawdown_pct": 5.0,
                                      "profit_factor": 2.0, "n_trades": 150,
                                      "significant": True, "total_return_pct": 12.0})
        run = TournamentRun(started_at="2026-06-11T10:00:00", config_hash="abc")
        run.reports = [rep]
        run.ranked = rank_reports([rep])
        return run

    monkeypatch.setattr(webapp, "run_tournament", fake_run_tournament)
    return TestClient(webapp.app)


def test_latest_empty_404(client):
    assert client.get("/api/tournament/latest").status_code == 404


def test_run_then_latest_and_list(client):
    r = client.post("/api/tournament/run")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    latest = client.get("/api/tournament/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["reports"][0]["name"] == "fake"
    assert body["reports"][0]["gates"]["passed"] is True
    runs = client.get("/api/tournament/runs").json()
    assert len(runs["runs"]) == 1
```

- [ ] **Step 2: Run to verify FAIL** — `.venv/bin/python -m pytest backend/tests/test_tournament_api.py -q` → AttributeError/404s (endpoints missing).

- [ ] **Step 3: Add endpoints to `backend/web/app.py`**

Near the other imports at the top of the file add:

```python
from backend.backtest.tournament import (
    DEFAULT_STORE as TOURNAMENT_STORE_DEFAULT, list_runs as tournament_list_runs,
    load_latest as tournament_load_latest, run_tournament, save_run as tournament_save_run,
)

TOURNAMENT_STORE = TOURNAMENT_STORE_DEFAULT
_tournament_state: dict = {"running": False, "progress": "", "error": ""}
```

After the `/api/scan` endpoint add:

```python
@app.post("/api/tournament/run")
def api_tournament_run(background_tasks: BackgroundTasks):
    """Kick off a tournament in the background. Idempotent while running."""
    if _tournament_state["running"]:
        return {"ok": False, "running": True, "progress": _tournament_state["progress"]}

    def _job():
        _tournament_state.update(running=True, progress="starting", error="")
        try:
            cfg = load_config()   # use the module's existing config loader name
            run = run_tournament(
                cfg,
                progress=lambda name, i, total: _tournament_state.update(
                    progress=f"{name} ({i}/{total})"),
            )
            tournament_save_run(run, store_dir=TOURNAMENT_STORE)
        except Exception as exc:  # noqa: BLE001 — surfaced via status, not lost
            _tournament_state["error"] = str(exc)
        finally:
            _tournament_state["running"] = False

    background_tasks.add_task(_job)
    return {"ok": True, "running": True}


@app.get("/api/tournament/latest")
def api_tournament_latest():
    data = tournament_load_latest(store_dir=TOURNAMENT_STORE)
    if data is None:
        raise HTTPException(status_code=404, detail="no tournament runs yet")
    data["status"] = dict(_tournament_state)
    return data


@app.get("/api/tournament/runs")
def api_tournament_runs():
    return {"runs": tournament_list_runs(store_dir=TOURNAMENT_STORE),
            "status": dict(_tournament_state)}
```

**Implementer notes:**
- `BackgroundTasks` and `HTTPException` come from `fastapi` — extend the existing import line.
- `load_config()`: app.py already loads `config.yaml` somewhere near startup (the `/api/config` endpoint at line ~979 reads it). Reuse THAT existing function/variable rather than inventing a new loader; if it's a module-level `CONFIG` dict, pass that. In the test, `run_tournament` is monkeypatched so config loading is not exercised — but wire it correctly for real runs.
- Because the test monkeypatches `webapp.run_tournament`, call it via the module-level name exactly as imported above (i.e. `run_tournament(...)`, not a re-import inside `_job`). Python name lookup at call time makes the monkeypatch effective — keep the call unqualified.

- [ ] **Step 4: Run tests, commit**

Run: `.venv/bin/python -m pytest backend/tests/test_tournament_api.py backend/tests/ -q` → PASS.

```bash
git add backend/web/app.py backend/tests/test_tournament_api.py
git commit -m "feat(api): tournament run/latest/runs endpoints"
```

---

### Task 12: `/tournament` frontend page

**Files:**
- Modify: `frontend/lib/api.ts` (helpers), `frontend/lib/types.ts` (types), `frontend/components/shell/sidebar.tsx` (nav entry)
- Create: `frontend/components/core/tournament-client.tsx`
- Create: `frontend/app/tournament/page.tsx`

No test runner is configured for the frontend; verification is `pnpm --dir frontend build` + manual check.

- [ ] **Step 1: Add types to `frontend/lib/types.ts`** (append):

```typescript
export type TournamentGate = {
  passed: boolean;
  failures: string[];
};

export type TournamentReport = {
  name: string;
  kind: "trades" | "portfolio" | "pairs";
  metrics: {
    oos_sharpe?: number;
    total_return_pct?: number;
    annual_return_pct?: number;
    max_drawdown_pct?: number;
    profit_factor?: number;
    n_trades?: number;
    n_rebalances?: number;
    significant?: boolean;
    [k: string]: unknown;
  };
  equity_curve: [string, number][];
  windows: { year?: number; return_pct?: number }[];
  gates: TournamentGate | null;
  error: string;
};

export type TournamentLatest = {
  started_at: string;
  config_hash: string;
  reports: TournamentReport[];
  status?: { running: boolean; progress: string; error: string };
};

export type TournamentRuns = {
  runs: { file: string; started_at: string; n_strategies: number }[];
  status?: { running: boolean; progress: string; error: string };
};
```

- [ ] **Step 2: Add API helpers to `frontend/lib/api.ts`** (append; the `api<T>` helper already exists):

```typescript
export function getTournamentLatest() {
  return api<TournamentLatest>("/api/tournament/latest");
}

export function getTournamentRuns() {
  return api<TournamentRuns>("/api/tournament/runs");
}

export function runTournament() {
  return api<{ ok: boolean; running: boolean }>("/api/tournament/run", {
    method: "POST",
  });
}
```

And extend the type import at the top of `api.ts`:

```typescript
import type {
  // ...existing names...
  TournamentLatest,
  TournamentRuns,
} from "@/lib/types";
```

- [ ] **Step 3: Create `frontend/components/core/tournament-client.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";

import { getTournamentLatest, runTournament } from "@/lib/api";
import type { TournamentLatest, TournamentReport } from "@/lib/types";
import { cn } from "@/lib/utils";

function Sparkline({ curve }: { curve: [string, number][] }) {
  if (!curve || curve.length < 2) return <span className="text-muted-foreground">—</span>;
  const vals = curve.map(([, v]) => v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals
    .map((v, i) => `${(i / (vals.length - 1)) * 100},${28 - ((v - min) / span) * 26}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" className="h-7 w-24" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5"
        className={vals[vals.length - 1] >= vals[0] ? "text-emerald-500" : "text-red-500"} />
    </svg>
  );
}

function GateBadges({ report }: { report: TournamentReport }) {
  if (report.error) {
    return <span className="rounded bg-red-500/15 px-2 py-0.5 text-xs text-red-500">error</span>;
  }
  if (report.gates?.passed) {
    return <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-500">all gates passed</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {report.gates?.failures.map((f) => (
        <span key={f} className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-600">
          {f}
        </span>
      ))}
    </div>
  );
}

const fmt = (v: number | undefined, digits = 2) =>
  v === undefined || v === null ? "—" : v.toFixed(digits);

export function TournamentClient({ initial }: { initial: TournamentLatest | null }) {
  const [data, setData] = useState<TournamentLatest | null>(initial);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await getTournamentLatest());
    } catch {
      /* 404 until the first run exists */
    }
  }, []);

  useEffect(() => {
    if (!data?.status?.running) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [data?.status?.running, refresh]);

  const onRun = async () => {
    setBusy(true);
    try {
      await runTournament();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onRun}
          disabled={busy || data?.status?.running}
          className={cn(
            "rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground",
            (busy || data?.status?.running) && "opacity-50",
          )}
        >
          {data?.status?.running ? `Running… ${data.status.progress}` : "Run tournament"}
        </button>
        {data?.started_at && (
          <span className="text-sm text-muted-foreground">
            Last run {data.started_at} · config {data.config_hash}
          </span>
        )}
        {data?.status?.error && (
          <span className="text-sm text-red-500">{data.status.error}</span>
        )}
      </div>

      {!data ? (
        <p className="text-sm text-muted-foreground">
          No tournament runs yet. Run one to rank every strategy on out-of-sample results.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-secondary/50 text-left text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2">#</th>
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Kind</th>
                <th className="px-3 py-2 text-right">OOS Sharpe</th>
                <th className="px-3 py-2 text-right">Return %</th>
                <th className="px-3 py-2 text-right">Max DD %</th>
                <th className="px-3 py-2 text-right">PF</th>
                <th className="px-3 py-2 text-right">Trades</th>
                <th className="px-3 py-2">Equity</th>
                <th className="px-3 py-2">Gates</th>
              </tr>
            </thead>
            <tbody>
              {data.reports.map((r, i) => (
                <tr
                  key={r.name}
                  className={cn("border-t", !r.gates?.passed && "opacity-50")}
                >
                  <td className="px-3 py-2 tabular-nums">{i + 1}</td>
                  <td className="px-3 py-2 font-medium">{r.name}</td>
                  <td className="px-3 py-2 text-muted-foreground">{r.kind}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(r.metrics.oos_sharpe)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(r.metrics.total_return_pct, 1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(r.metrics.max_drawdown_pct, 1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{fmt(r.metrics.profit_factor)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.kind === "portfolio" ? r.metrics.n_rebalances ?? "—" : r.metrics.n_trades ?? "—"}
                  </td>
                  <td className="px-3 py-2"><Sparkline curve={r.equity_curve} /></td>
                  <td className="px-3 py-2"><GateBadges report={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Out-of-sample results only. Greyed rows failed a hard gate (named in the badge) —
        shown anyway so nothing hides. Rankings are estimated edge, not a guarantee.
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Create `frontend/app/tournament/page.tsx`**

```tsx
import { TournamentClient } from "@/components/core/tournament-client";
import { PageTitle } from "@/components/shell/page-title";
import { getTournamentLatest } from "@/lib/api";

export default async function TournamentPage() {
  const latest = await getTournamentLatest().catch(() => null);

  return (
    <>
      <PageTitle
        title="Strategy Tournament"
        description="Walk every strategy through out-of-sample validation; rank by OOS Sharpe with hard risk gates."
      />
      <TournamentClient initial={latest} />
    </>
  );
}
```

- [ ] **Step 5: Add nav entry in `frontend/components/shell/sidebar.tsx`**

Add `Trophy` to the lucide-react import list, then in the `Validation` group change items to:

```tsx
  {
    label: "Validation",
    items: [
      { href: "/backtest", label: "Backtest & Validation", icon: LineChart },
      { href: "/tournament", label: "Tournament", icon: Trophy },
    ],
  },
```

- [ ] **Step 6: Build + verify**

Run: `pnpm --dir frontend build`
Expected: build succeeds (the page server-fetch catches the 404 and renders the empty state).

Manual check: `uvicorn backend.web.app:app` + `pnpm --dir frontend dev`, open `http://localhost:3000/tournament`, click **Run tournament**, watch progress, confirm the leaderboard renders with gate badges and sparklines.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/core/tournament-client.tsx frontend/app/tournament/page.tsx frontend/components/shell/sidebar.tsx
git commit -m "feat(web): /tournament leaderboard page"
```

---

### Task 13: Full-suite verification + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole backend suite**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: all green.

- [ ] **Step 2: Frontend build**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Update README**

In `README.md` under "What It Includes" add:

```markdown
- Strategy tournament: 6 US-equity strategies (ORB, gap-and-go, cross-sectional
  momentum, sector rotation, earnings drift, pairs stat-arb) ranked by
  out-of-sample Sharpe behind hard risk gates, with a `/tournament` leaderboard.
```

In the "Frontend routes" list add:

```markdown
- `/tournament` strategy tournament leaderboard
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: tournament + new US-equity strategies in README"
```
