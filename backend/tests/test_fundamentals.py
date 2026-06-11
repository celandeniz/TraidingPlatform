"""FundamentalsProvider: cached metric subset; typed failure; field tolerance."""
from __future__ import annotations

import json
import time

import pytest

from backend.data.fundamentals import (
    FundamentalsProvider, FundamentalsUnavailable, METRIC_KEYS,
)


def _info(**overrides):
    base = {
        "trailingPE": 28.5, "forwardPE": 25.1, "pegRatio": 1.8,
        "priceToBook": 12.0, "returnOnEquity": 0.45, "profitMargins": 0.24,
        "operatingMargins": 0.30, "debtToEquity": 140.0,
        "freeCashflow": 9.9e10, "revenueGrowth": 0.08, "earningsGrowth": 0.10,
        "marketCap": 3.1e12, "dividendYield": 0.005, "beta": 1.2,
        "fiftyTwoWeekHigh": 240.0, "fiftyTwoWeekLow": 160.0,
        "irrelevantField": "ignored",
    }
    base.update(overrides)
    return base


def test_get_fetches_once_caches_and_subsets(tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return _info()

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch)
    f1 = p.get("AAPL")
    f2 = p.get("AAPL")
    assert calls == ["AAPL"]                      # second call from cache
    assert f1 == f2
    assert set(f1) <= set(METRIC_KEYS)            # only whitelisted metrics
    assert "irrelevantField" not in f1
    assert f1["trailingPE"] == 28.5


def test_missing_fields_tolerated(tmp_path):
    p = FundamentalsProvider(tmp_path, fetch_fn=lambda s: {"trailingPE": 10.0})
    f = p.get("MSFT")
    assert f == {"trailingPE": 10.0}              # no crash, no padding


def test_ttl_expiry_refetches(tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return _info()

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch, ttl_hours=24)
    p.get("NVDA")
    # age the cache file beyond the TTL
    f = p._path("NVDA")
    data = json.loads(f.read_text())
    data["fetched_at"] = time.time() - 25 * 3600
    f.write_text(json.dumps(data))
    p.get("NVDA")
    assert calls == ["NVDA", "NVDA"]


def test_fetch_failure_raises_unavailable(tmp_path):
    def fetch(symbol):
        raise RuntimeError("rate limited")

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch)
    with pytest.raises(FundamentalsUnavailable):
        p.get("TSLA")
