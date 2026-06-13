"""Volume confirmation — grades a fired signal by participation.

A breakout/fade backed by above-average volume is more trustworthy. Passes when
the latest bar's volume exceeds `mult` x the rolling-average volume. Direction-
agnostic (volume confirms either side). Pure scoring in score_volume().
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, Confirmation, Side


def score_volume(df: pd.DataFrame, *, window: int = 20, mult: float = 1.5) -> dict:
    """Ratio of latest volume to its rolling average; passed if >= mult."""
    vol = df.get("volume")
    if vol is None or len(vol) < window + 1:
        return {"ratio": None, "passed": False}
    # Baseline excludes the current bar so a spike isn't diluted by itself.
    avg = vol.shift(1).rolling(window).mean().iloc[-1]
    if pd.isna(avg) or avg <= 0:
        return {"ratio": None, "passed": False}
    ratio = float(vol.iloc[-1] / avg)
    return {"ratio": ratio, "passed": ratio >= mult}


class VolumeConfirmStrategy:
    name = "volume"

    def confirm(self, side: Side, ctx: BarContext) -> Confirmation:
        p = ctx.config.get("volume", {})
        res = score_volume(ctx.window, window=p.get("window", 20), mult=p.get("mult", 1.5))
        return Confirmation(
            name=self.name,
            score=float(res["ratio"]) if res["ratio"] is not None else 0.0,
            passed=res["passed"],
            meta={"volume_ratio": res["ratio"]},
        )
