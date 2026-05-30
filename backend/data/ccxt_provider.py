"""ccxt crypto DataProvider — same Protocol as AlpacaProvider, crypto venues.

Returns the identical OHLCV DataFrame contract (open/high/low/close/volume,
tz-aware UTC index) so strategies/indicators don't care it's crypto. Default
target is Binance testnet (sandbox). Symbols use ccxt form, e.g. "BTC/USDT".
"""
from __future__ import annotations

import asyncio

import pandas as pd

from .base import BarHandler

# ccxt timeframe strings already match ours: 1m,3m,5m,15m,1h... but Alpaca-style
# "45m" is not a native crypto candle — callers should use crypto-native frames.
_TF_MAP = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d"}


class CcxtDataProvider:
    def __init__(self, exchange: str = "binance", api_key: str = "", api_secret: str = "",
                 sandbox: bool = True):
        import ccxt

        klass = getattr(ccxt, exchange)
        self._exchange = klass({
            "apiKey": api_key, "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},  # futures = native short/leverage
        })
        if sandbox and self._exchange.has.get("sandbox", True):
            self._exchange.set_sandbox_mode(True)

    def get_recent_bars(self, symbol: str, timeframe: str, lookback: int) -> pd.DataFrame:
        tf = _TF_MAP.get(timeframe, timeframe)
        try:
            raw = self._exchange.fetch_ohlcv(symbol, timeframe=tf, limit=lookback)
        except Exception:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if not raw:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df[["open", "high", "low", "close", "volume"]].tail(lookback)

    async def stream_bars(self, symbols: list[str], handler: BarHandler) -> None:
        """Poll-based stream (ccxt REST). For true websockets use ccxt.pro.

        Emits a bar each time a new candle close appears per symbol.
        """
        last_ts: dict[str, int] = {}
        while True:
            for sym in symbols:
                df = self.get_recent_bars(sym, "1m", 2)
                if df.empty:
                    continue
                ts = int(df.index[-1].timestamp())
                if last_ts.get(sym) == ts:
                    continue
                last_ts[sym] = ts
                row = df.iloc[-1]
                await handler(sym, {
                    "timestamp": df.index[-1], "open": row["open"], "high": row["high"],
                    "low": row["low"], "close": row["close"], "volume": row["volume"],
                })
            await asyncio.sleep(5)
