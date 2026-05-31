"""Keltner Channel breakout (volatility-adjusted trend). Close pierces the band."""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import keltner


def generate(df: pd.DataFrame, *, period: int = 20, mult: float = 2.0) -> dict:
    """Buy when close breaks above the upper Keltner band, sell below lower."""
    if len(df) < period + 2:
        return {"buy": False, "sell": False, "close": None}
    _, upper, lower = keltner(df, period, mult)
    c = df["close"].iloc[-1]
    buy = bool(c > upper.iloc[-1])
    sell = bool(c < lower.iloc[-1])
    return {"buy": buy, "sell": sell, "close": float(c)}


class KeltnerBreakoutStrategy:
    name = "keltner_breakout"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("keltner_breakout", {})
        res = generate(ctx.window, period=p.get("period", 20), mult=p.get("mult", 2.0))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0,
                              meta={"keltner_close": res["close"]})
