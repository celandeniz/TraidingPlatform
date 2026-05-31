"""VWAP reversion: price stretched far from VWAP tends to snap back (mean-rev).

Buy when price is `band_pct` below VWAP and ticks up; sell when `band_pct` above
and ticks down. Intraday-natural since VWAP anchors to the session's volume.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import vwap


def generate(df: pd.DataFrame, *, band_pct: float = 1.0) -> dict:
    """Needs columns: high, low, close, volume."""
    if len(df) < 20:
        return {"buy": False, "sell": False, "dist_pct": None}
    vw = vwap(df)
    close = df["close"]
    dist = (close.iloc[-1] / vw.iloc[-1] - 1.0) * 100.0 if vw.iloc[-1] else 0.0
    up = close.iloc[-1] > close.iloc[-2]
    down = close.iloc[-1] < close.iloc[-2]
    buy = bool(dist <= -abs(band_pct) and up)    # stretched below, turning up
    sell = bool(dist >= abs(band_pct) and down)  # stretched above, turning down
    return {"buy": buy, "sell": sell, "dist_pct": round(float(dist), 3)}


class VwapReversionStrategy:
    name = "vwap_reversion"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("vwap_reversion", {})
        res = generate(ctx.window, band_pct=p.get("band_pct", 1.0))
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        return StrategySignal(side=side,
                              strength=abs(res["dist_pct"]) if res["dist_pct"] else 0.0,
                              meta={"vwap_dist_pct": res["dist_pct"]})
