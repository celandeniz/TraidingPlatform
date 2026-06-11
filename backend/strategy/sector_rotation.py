"""Sector rotation over the 11 SPDR sector ETFs.

Monthly: rank ETFs by blended momentum (mean of 3-, 6-, 12-month returns), hold
the top_n equal-weight. Same SPY 200-day cash filter as xs_momentum.
"""
from __future__ import annotations

import pandas as pd

from .base import UniverseContext
from .xs_momentum import regime_ok

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
               "XLI", "XLB", "XLRE", "XLU", "XLC"]
WINDOWS = (63, 126, 252)             # ~3, 6, 12 months of trading days


def blended_momentum(close: pd.Series) -> float:
    return float(sum(close.iloc[-1] / close.iloc[-w] - 1.0 for w in WINDOWS) / len(WINDOWS))


class SectorRotationStrategy:
    name = "sector_rotation"

    def rebalance(self, ctx: UniverseContext) -> dict:
        p = ctx.config.get("sector_rotation", {})
        etfs = p.get("etfs", SECTOR_ETFS)
        top_n = p.get("top_n", 3)
        if p.get("regime_filter", True) and not regime_ok(
                ctx.frames, benchmark=p.get("benchmark", "SPY")):
            return {}
        scores = {}
        for sym in etfs:
            df = ctx.frames.get(sym)
            if df is None or len(df) < max(WINDOWS) + 1:
                continue
            scores[sym] = blended_momentum(df["close"])
        winners = sorted(scores, key=scores.get, reverse=True)[:top_n]
        if not winners:
            return {}
        w = 1.0 / len(winners)
        return {s: w for s in winners}
