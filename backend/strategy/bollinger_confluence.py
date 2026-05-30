"""Multi-timeframe Bollinger Band confirmation.

Grades a fired spike-fade signal: count timeframes whose latest close sits on the
"agreeing" side of its band.

  buy  agrees when close < lower band (oversold)
  sell agrees when close > upper band (overbought)

score = number of agreeing timeframes; confirmed = score >= confirm_min.
Pure scoring lives in score_confluence(); the Strategy adapter pulls per-TF bars
through the context.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, Confirmation, Side
from .indicators import bollinger


def _band_position(close_val: float, lower: float, upper: float) -> str:
    if pd.isna(lower) or pd.isna(upper) or pd.isna(close_val):
        return "unknown"
    if close_val < lower:
        return "below_lower"
    if close_val > upper:
        return "above_upper"
    return "in_band"


def score_confluence(
    side: Side,
    per_tf_bars: dict[str, pd.DataFrame],
    *,
    period: int = 20,
    std: float = 2.0,
    confirm_min: int = 3,
) -> dict:
    """Score band agreement across timeframes.

    per_tf_bars: {"5m": df, ...} each oldest..newest with a 'close' column.
    Returns {"bb_score", "bb_confirmed", "bb_per_tf"}.
    """
    agree_pos = "below_lower" if side == "buy" else "above_upper"
    per_tf: dict[str, str] = {}
    score = 0
    for tf, df in per_tf_bars.items():
        if df is None or len(df) < period:
            per_tf[tf] = "unknown"
            continue
        _, upper, lower = bollinger(df["close"], period, std)
        pos = _band_position(df["close"].iloc[-1], lower.iloc[-1], upper.iloc[-1])
        per_tf[tf] = pos
        if pos == agree_pos:
            score += 1
    return {
        "bb_score": score,
        "bb_confirmed": score >= confirm_min,
        "bb_per_tf": per_tf,
    }


class BollingerConfluenceStrategy:
    name = "bollinger"

    def confirm(self, side: Side, ctx: BarContext) -> Confirmation:
        cfg = ctx.config.get("bollinger", {})
        period = cfg.get("period", 20)
        std = cfg.get("std", 2.0)
        confirm_min = cfg.get("confirm_min", 3)
        timeframes = cfg.get("timeframes", ["1m", "3m", "5m", "15m", "45m", "1h"])

        per_tf_bars = {tf: ctx.get_bars(tf, period + 5) for tf in timeframes}
        res = score_confluence(
            side, per_tf_bars, period=period, std=std, confirm_min=confirm_min
        )
        return Confirmation(
            name=self.name,
            score=float(res["bb_score"]),
            passed=res["bb_confirmed"],
            meta={"bb_per_tf": res["bb_per_tf"], "bb_score": res["bb_score"]},
        )
