"""Donchian channel breakout signal — a second trend/momentum strategy.

Close breaking ABOVE the highest high of the prior N bars = buy (breakout up);
breaking BELOW the lowest low of the prior N bars = sell (breakdown). Classic
turtle-style breakout, complementary to mean-reversion.

Pure logic in generate(); DonchianBreakoutStrategy adapts it to the interface.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal


def generate(df: pd.DataFrame, *, channel: int = 20) -> dict:
    """Breakout of the prior `channel` bars' range, evaluated on the last bar.

    Needs columns: high, low, close. The prior range EXCLUDES the current bar
    (shift by 1) so the breakout is genuine, not self-referential.
    """
    if len(df) < channel + 1:
        return {"buy": False, "sell": False, "close": None}
    prior_high = df["high"].shift(1).rolling(channel).max()
    prior_low = df["low"].shift(1).rolling(channel).min()
    close = df["close"]
    buy = bool(close.iloc[-1] > prior_high.iloc[-1])
    sell = bool(close.iloc[-1] < prior_low.iloc[-1])
    return {"buy": buy, "sell": sell, "close": float(close.iloc[-1])}


class DonchianBreakoutStrategy:
    name = "donchian_breakout"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("donchian_breakout", {})
        res = generate(ctx.window, channel=p.get("channel", 20))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0,
                              meta={"breakout_close": res["close"]})
