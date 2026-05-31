"""ATR-channel trend follow: price closing beyond a recent EMA +/- k*ATR band
in the trend direction = momentum entry. Volatility-scaled, so it adapts across
timeframes (1m vs 45m) without re-tuning a fixed price distance.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import atr, ema


def generate(df: pd.DataFrame, *, period: int = 20, k: float = 1.5) -> dict:
    """Buy when close > EMA + k*ATR (trend thrust up), sell when < EMA - k*ATR."""
    if len(df) < period + 2:
        return {"buy": False, "sell": False, "close": None}
    mid = ema(df["close"], period)
    a = atr(df, period)
    c = df["close"].iloc[-1]
    up_band = mid.iloc[-1] + k * a.iloc[-1]
    dn_band = mid.iloc[-1] - k * a.iloc[-1]
    buy = bool(c > up_band)
    sell = bool(c < dn_band)
    return {"buy": buy, "sell": sell, "close": float(c)}


class AtrTrendStrategy:
    name = "atr_trend"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("atr_trend", {})
        res = generate(ctx.window, period=p.get("period", 20), k=p.get("k", 1.5))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0,
                              meta={"atr_close": res["close"]})
