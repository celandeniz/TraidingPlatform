"""Yahoo provider — no network. A fake yfinance is injected to bypass the lazy import."""
import types

import pandas as pd

from backend.marketdata.yahoo_provider import YahooProvider


class _FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period=None, interval=None, auto_adjust=False):
        return pd.DataFrame({
            "Open": [1.0, 2.0], "High": [1.5, 2.5], "Low": [0.5, 1.5],
            "Close": [1.2, 2.2], "Volume": [100, 200]},
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]))

    @property
    def info(self):
        return {"longName": "Apple Inc", "sector": "Technology", "industry": "HW",
                "marketCap": 3.0e12, "trailingPE": 28.5, "debtToEquity": 1.2,
                "profitMargins": 0.25}

    @property
    def news(self):
        return [{"providerPublishTime": 1704110400,
                 "content": {"title": "Apple hits record", "summary": "up",
                             "canonicalUrl": {"url": "http://news/aapl"}}}]


def _provider():
    p = YahooProvider()
    fake = types.ModuleType("yfinance")
    fake.Ticker = _FakeTicker
    p._yf = fake  # inject; bypasses lazy `import yfinance`
    return p


def test_recent_bars_normalized_lowercase_ohlcv():
    df = _provider().get_recent_bars("AAPL", "1d", lookback=10)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[-1] == 2.2


def test_fundamentals_from_info():
    f = _provider().get_fundamentals("AAPL")
    assert f.name == "Apple Inc" and f.sector == "Technology"
    assert f.pe_ratio == 28.5 and f.profit_margin == 0.25


def test_news_maps_to_headlines():
    news = _provider().get_news("AAPL")
    assert len(news) == 1
    assert news[0].headline == "Apple hits record"
    assert news[0].url == "http://news/aapl" and news[0].symbol == "AAPL"
