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
