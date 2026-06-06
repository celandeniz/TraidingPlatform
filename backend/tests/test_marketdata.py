"""Market-data layer tests — no network. A fake obb client stands in for OpenBB."""
import pandas as pd

from backend.marketdata.factory import build_market_data_provider
from backend.marketdata.openbb_provider import OpenBBProvider


class _OBBject:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class _FakeOBB:
    """Minimal stand-in mirroring the obb.<asset>.<...> call surface we use."""

    def __init__(self):
        bars = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.5, 1.5],
            "close": [1.2, 2.2], "volume": [100, 200],
        })
        self._bars = bars
        self.equity = _Ns(
            price=_Ns(historical=lambda *a, **k: _OBBject(bars)),
            search=lambda q, **k: _OBBject(pd.DataFrame(
                {"symbol": ["AAPL"], "name": ["Apple Inc"], "exchange": ["NASDAQ"]})),
            profile=lambda s, **k: _OBBject(pd.DataFrame(
                {"name": ["Apple Inc"], "sector": ["Tech"], "industry": ["HW"],
                 "market_cap": [3.0e12]})),
            fundamental=_Ns(ratios=lambda s, **k: _OBBject(pd.DataFrame(
                {"price_to_earnings": [28.5], "debt_to_equity": [1.2],
                 "net_profit_margin": [0.25]}))),
            ownership=_Ns(insider_trading=lambda s, **k: _OBBject(pd.DataFrame(
                {"name": ["CEO"], "shares": [1000]}))),
            discovery=_Ns(gainers=lambda **k: _OBBject(pd.DataFrame(
                {"symbol": ["NVDA"], "change_percent": [5.0]}))),
            calendar=_Ns(earnings=lambda **k: _OBBject(pd.DataFrame(
                {"symbol": ["MSFT"], "report_date": ["2024-01-25"]}))),
        )


class _Ns:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _provider():
    p = OpenBBProvider()
    p._obb = _FakeOBB()  # inject fake; bypasses the lazy `from openbb import obb`
    return p


def test_recent_bars_normalized_to_ohlcv():
    df = _provider().get_recent_bars("AAPL", "1d", lookback=10)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2 and df["close"].iloc[-1] == 2.2


def test_search_symbols():
    matches = _provider().search_symbols("apple")
    assert matches and matches[0].symbol == "AAPL" and matches[0].name == "Apple Inc"


def test_fundamentals_merges_profile_and_ratios():
    f = _provider().get_fundamentals("AAPL")
    assert f.name == "Apple Inc" and f.sector == "Tech"
    assert f.pe_ratio == 28.5 and f.debt_to_equity == 1.2 and f.profit_margin == 0.25


def test_movers_and_calendar_and_insider():
    p = _provider()
    assert not p.get_market_movers("gainers").empty
    assert not p.get_earnings_calendar().empty
    assert not p.get_insider_trading("AAPL").empty


def test_factory_disabled_returns_none():
    assert build_market_data_provider(object(), {"marketdata": {"enabled": False}}) is None
    assert build_market_data_provider(object(), {}) is None
