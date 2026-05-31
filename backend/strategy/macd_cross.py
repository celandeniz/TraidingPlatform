"""MACD signal-line crossover (momentum). Histogram flips sign => signal."""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import macd


def generate(df: pd.DataFrame, *, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Buy when MACD crosses above its signal line, sell when below (last bar)."""
    close = df["close"]
    if len(close) < slow + signal + 2:
        return {"buy": False, "sell": False, "hist": None}
    _, _, hist = macd(close, fast, slow, signal)
    prev, now = hist.iloc[-2], hist.iloc[-1]
    buy = bool(prev <= 0 < now)
    sell = bool(prev >= 0 > now)
    return {"buy": buy, "sell": sell, "hist": None if pd.isna(now) else float(now)}


class MacdCrossStrategy:
    name = "macd_cross"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("macd_cross", {})
        res = generate(ctx.window, fast=p.get("fast", 12), slow=p.get("slow", 26),
                       signal=p.get("signal", 9))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side, strength=abs(res["hist"]) if res["hist"] else 0.0,
                              meta={"macd_hist": res["hist"]})
