"""Alpaca implementation of DataProvider.

Live 1m bars via the stock-data websocket; historical pulls via the REST data
client (warmup + multi-timeframe Bollinger). Timeframe strings like "3m"/"45m"/
"1h" map to Alpaca's custom TimeFrame amounts.
"""
from __future__ import annotations

import re

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from .base import BarHandler

_UNIT = {
    "m": TimeFrameUnit.Minute,
    "min": TimeFrameUnit.Minute,
    "h": TimeFrameUnit.Hour,
    "d": TimeFrameUnit.Day,
}


def parse_timeframe(tf: str) -> TimeFrame:
    """'1m'->1Min, '3m'->3Min, '45m'->45Min, '1h'->1Hour."""
    m = re.fullmatch(r"(\d+)\s*([a-zA-Z]+)", tf.strip())
    if not m:
        raise ValueError(f"Bad timeframe: {tf!r}")
    amount, unit = int(m.group(1)), m.group(2).lower()
    if unit not in _UNIT:
        raise ValueError(f"Unsupported timeframe unit in {tf!r}")
    return TimeFrame(amount, _UNIT[unit])


def _lookback_minutes(tf: str, bars: int) -> int:
    amount, unit = re.fullmatch(r"(\d+)\s*([a-zA-Z]+)", tf.strip()).groups()
    amount = int(amount)
    per_bar_min = amount * (60 if unit.lower().startswith("h") else 1)
    return per_bar_min * bars


class AlpacaProvider:
    def __init__(self, api_key: str, api_secret: str, feed: str = "iex"):
        self._key = api_key
        self._secret = api_secret
        self._feed = feed
        self._hist = StockHistoricalDataClient(api_key, api_secret)
        self._stream: StockDataStream | None = None

    def get_recent_bars(
        self, symbol: str, timeframe: str, lookback: int
    ) -> pd.DataFrame:
        # Pad the window generously so we still get `lookback` bars despite
        # nights/weekends/holidays, then trim to the last `lookback`.
        minutes = _lookback_minutes(timeframe, lookback)
        start = pd.Timestamp.utcnow() - pd.Timedelta(minutes=minutes * 6 + 6000)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=parse_timeframe(timeframe),
            start=start.to_pydatetime(),
            feed=self._feed,
        )
        bars = self._hist.get_stock_bars(req)
        df = bars.df
        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")
        df = df[["open", "high", "low", "close", "volume"]].tail(lookback)
        return df

    async def stream_bars(self, symbols: list[str], handler: BarHandler) -> None:
        self._stream = StockDataStream(self._key, self._secret, feed=self._feed)

        async def _on_bar(bar):
            await handler(
                bar.symbol,
                {
                    "timestamp": bar.timestamp,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                },
            )

        self._stream.subscribe_bars(_on_bar, *symbols)
        await self._stream._run_forever()
