"""EMA momentum / trend-follow signal — complements the mean-reverting spike-fade.

Fast EMA crossing ABOVE slow EMA = buy (uptrend starting); crossing BELOW = sell.
Where spike-fade fades extremes, this rides trends — useful in trending regimes
the fade strategy struggles with.

Pure logic in generate(); EmaMomentumStrategy adapts it to the SignalStrategy
interface.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import ema


def generate(df: pd.DataFrame, *, fast: int = 12, slow: int = 26) -> dict:
    """Detect an EMA crossover on the last closed bar. Needs column: close."""
    close = df["close"]
    if len(close) < slow + 1:
        return {"buy": False, "sell": False, "spread": None}
    ef = ema(close, fast)
    es = ema(close, slow)
    spread_now = ef.iloc[-1] - es.iloc[-1]
    spread_prev = ef.iloc[-2] - es.iloc[-2]
    buy = bool(spread_prev <= 0 and spread_now > 0)   # crossed up
    sell = bool(spread_prev >= 0 and spread_now < 0)  # crossed down
    return {"buy": buy, "sell": sell, "spread": _safe(spread_now)}


def _safe(x):
    return None if pd.isna(x) else float(x)


class EmaMomentumStrategy:
    name = "ema_momentum"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("ema_momentum", {})
        res = generate(ctx.window, fast=p.get("fast", 12), slow=p.get("slow", 26))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(
            side=side,
            strength=abs(res["spread"]) if res["spread"] is not None else 0.0,
            meta={"ema_spread": res["spread"]},
        )
