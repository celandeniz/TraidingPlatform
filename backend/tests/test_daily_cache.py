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


# ---------------------------------------------------------------------------
# C1: empty CSV → cache miss → refetch (no AttributeError crash)
# ---------------------------------------------------------------------------

def test_empty_csv_treated_as_cache_miss(tmp_path):
    """First fetch returns empty; second call with a working fetch_fn succeeds."""
    call_count = [0]

    def fetch(symbol, start, end):
        call_count[0] += 1
        if call_count[0] == 1:
            # Simulate a fetch that returns nothing (e.g. market closed window)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _daily(200)

    cache = DailyBarCache(tmp_path, fetch_fn=fetch)

    # First get: fetch returns empty → cache stays miss (no crash)
    df1 = cache.get("TSLA")
    assert df1.empty or len(df1) == 0

    # Second get: fetch_fn now returns real data → succeeds
    df2 = cache.get("TSLA")
    assert len(df2) == 200
    assert df2.index.tz is not None


# ---------------------------------------------------------------------------
# I1: path traversal — symbol "../evil" must not escape tmp_path
# ---------------------------------------------------------------------------

def test_path_traversal_symbol_sanitized(tmp_path):
    """get('../evil') must write inside tmp_path, never outside."""
    def fetch(symbol, start, end):
        return _daily(10)

    cache = DailyBarCache(tmp_path, fetch_fn=fetch)
    cache.get("../evil")

    # Must NOT create a file outside tmp_path
    outside = tmp_path.parent / "EVIL.csv"
    assert not outside.exists(), "path traversal escaped tmp_path!"

    # At least one .csv file must exist inside tmp_path
    csv_files = list(tmp_path.glob("*.csv"))
    assert csv_files, "no CSV written inside cache dir"


# ---------------------------------------------------------------------------
# I2: UTC enforcement — Eastern-indexed frame → UTC on return
# ---------------------------------------------------------------------------

def test_eastern_index_converted_to_utc(tmp_path):
    """fetch_fn returning a US/Eastern DatetimeIndex → get() returns UTC."""
    def fetch(symbol, start, end):
        idx = pd.bdate_range(end=date(2026, 6, 10), periods=50, tz="US/Eastern")
        return pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=idx,
        )

    cache = DailyBarCache(tmp_path, fetch_fn=fetch)
    df = cache.get("GS")
    assert str(df.index.tz) == "UTC", f"expected UTC, got {df.index.tz}"


def test_alpaca_creds_resolve_from_alpaca_env_names(monkeypatch):
    """Live-run regression: .env uses ALPACA_API_KEY/ALPACA_API_SECRET, not the
    alpaca-py APCA_* names — both spellings must resolve."""
    from backend.data.daily_cache import _alpaca_creds

    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY",
                 "ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "k123")
    monkeypatch.setenv("ALPACA_API_SECRET", "s456")
    assert _alpaca_creds() == ("k123", "s456")
