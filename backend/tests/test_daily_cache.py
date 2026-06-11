"""DailyBarCache: fetch-once CSV cache of daily OHLCV with coverage gating."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backend.data.daily_cache import DailyBarCache


def _daily(n_days: int, end: date | None = None) -> pd.DataFrame:
    end = end or date.today()
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
        return _daily(25, end=date.today())  # recent block

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
