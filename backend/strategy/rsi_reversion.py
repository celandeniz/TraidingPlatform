"""RSI mean-reversion: buy deeply oversold, sell deeply overbought.

Simpler than spike-fade (no z-score gate) — fires when RSI crosses back from an
extreme, catching exhaustion turns. Pure logic in generate().
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import rsi


def generate(df: pd.DataFrame, *, period: int = 14, oversold: float = 30.0,
             overbought: float = 70.0) -> dict:
    """Fire when RSI crosses UP through oversold (buy) or DOWN through overbought
    (sell) on the last closed bar. Needs column: close."""
    close = df["close"]
    if len(close) < period + 2:
        return {"buy": False, "sell": False, "rsi": None}
    r = rsi(close, period)
    prev, now = r.iloc[-2], r.iloc[-1]
    buy = bool(prev < oversold <= now)      # crossing back up out of oversold
    sell = bool(prev > overbought >= now)   # crossing back down out of overbought
    return {"buy": buy, "sell": sell, "rsi": None if pd.isna(now) else float(now)}


class RsiReversionStrategy:
    name = "rsi_reversion"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("rsi_reversion", {})
        res = generate(ctx.window, period=p.get("period", 14),
                       oversold=p.get("oversold", 30.0), overbought=p.get("overbought", 70.0))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0,
                              meta={"rsi": res["rsi"]})
