"""Spike-fade signal: fade a sudden move once it starts to reverse.

  buy  (long/CALL candidate): sudden DROP + oversold + reversal up
  sell (short/PUT candidate): sudden SPIKE + overbought + reversal down

Pure logic lives in generate(df). SpikeFadeStrategy is a thin adapter to the
pluggable SignalStrategy interface.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import rsi, zscore


def generate(
    df: pd.DataFrame,
    *,
    zscore_window: int = 20,
    lookback_k: int = 3,
    z_entry: float = 2.0,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
) -> dict:
    """Evaluate the spike-fade signal on the LAST (closed) bar of df.

    Returns {"buy", "sell", "z", "rsi"}. Needs columns: close.
    """
    close = df["close"]
    ret = close.pct_change()
    z = zscore(ret, zscore_window)
    r = rsi(close, rsi_period)

    z_min_k = z.rolling(lookback_k).min()
    z_max_k = z.rolling(lookback_k).max()
    rsi_min_k = r.rolling(lookback_k).min()
    rsi_max_k = r.rolling(lookback_k).max()
    reversal_up = close > close.shift(1)
    reversal_down = close < close.shift(1)

    i = -1
    buy = bool(
        (z_min_k.iloc[i] < -z_entry)
        and (rsi_min_k.iloc[i] < rsi_oversold)
        and reversal_up.iloc[i]
    )
    sell = bool(
        (z_max_k.iloc[i] > z_entry)
        and (rsi_max_k.iloc[i] > rsi_overbought)
        and reversal_down.iloc[i]
    )
    return {
        "buy": buy,
        "sell": sell,
        "z": _safe_float(z.iloc[i]),
        "rsi": _safe_float(r.iloc[i]),
    }


def _safe_float(x) -> float | None:
    return None if pd.isna(x) else float(x)


class SpikeFadeStrategy:
    name = "spike_fade"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        params = ctx.config.get("spike_fade", {})
        res = generate(
            ctx.window,
            zscore_window=params.get("zscore_window", 20),
            lookback_k=params.get("lookback_k", 3),
            z_entry=params.get("z_entry", 2.0),
            rsi_period=params.get("rsi_period", 14),
            rsi_oversold=params.get("rsi_oversold", 30.0),
            rsi_overbought=params.get("rsi_overbought", 70.0),
        )
        side = "buy" if res["buy"] else "sell" if res["sell"] else None
        strength = abs(res["z"]) if res["z"] is not None else 0.0
        return StrategySignal(
            side=side,
            strength=strength,
            meta={"z": res["z"], "rsi": res["rsi"]},
        )
