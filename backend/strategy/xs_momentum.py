"""Cross-sectional momentum — the most robust documented equity anomaly.

Monthly rebalance: rank the universe by 12-1 momentum (252-day return skipping
the most recent 21 days, to dodge short-term reversal), hold the top_n names
equal-weight. Regime filter: 100% cash while SPY < its 200-day MA.
"""
from __future__ import annotations

import pandas as pd

from .base import UniverseContext

LOOKBACK = 252
SKIP = 21
MIN_BARS = LOOKBACK + SKIP


def regime_ok(frames: dict, *, benchmark: str = "SPY", ma_days: int = 200) -> bool:
    """True when the benchmark closes above its ma_days moving average (or when
    the benchmark is missing — fail open so tests/universes without SPY work)."""
    bench = frames.get(benchmark)
    if bench is None or len(bench) < ma_days:
        return True
    close = bench["close"]
    return float(close.iloc[-1]) > float(close.rolling(ma_days).mean().iloc[-1])


def momentum_12_1(close: pd.Series) -> float:
    return float(close.iloc[-1 - SKIP] / close.iloc[-MIN_BARS] - 1.0)


class XsMomentumStrategy:
    name = "xs_momentum"

    def rebalance(self, ctx: UniverseContext) -> dict:
        p = ctx.config.get("xs_momentum", {})
        top_n = p.get("top_n", 20)
        benchmark = p.get("benchmark", "SPY")
        if p.get("regime_filter", True) and not regime_ok(ctx.frames, benchmark=benchmark):
            return {}
        scores = {}
        for sym, df in ctx.frames.items():
            if sym == benchmark or len(df) < MIN_BARS:
                continue
            scores[sym] = momentum_12_1(df["close"])
        winners = sorted(scores, key=scores.get, reverse=True)[:top_n]
        if not winners:
            return {}
        w = 1.0 / len(winners)
        return {s: w for s in winners}
