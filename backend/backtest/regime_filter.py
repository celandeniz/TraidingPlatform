"""Regime-filtered signal wrappers — the (A) strategy improvement.

The walk-forward failure mode was clear: mean-reversion strategies faded strong
trends out-of-sample and got run over, while breakout/momentum strategies bought
chop in range regimes. A regime filter aligns each strategy with the regime it
actually works in:

  * mean-reversion (spike-fade): allowed ONLY in a "range" regime; suppressed in
    trends (don't fade a freight train).
  * momentum / breakout (ema, donchian): take the signal ONLY in the direction of
    the prevailing trend (buy in up-trend, sell in down-trend); suppressed in range.

Each wrapper sees the SAME no-lookahead window the base signal sees, computes the
regime on that window (past+current only), and zeroes out misaligned signals.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from ..strategy.regime import detect as detect_regime

SignalFn = Callable[[pd.DataFrame], dict]


def range_only(fn: SignalFn, *, ema_period: int = 50, slope_threshold: float = 0.0008) -> SignalFn:
    """Mean-reversion: only fire when the regime is 'range'."""
    def wrapped(df: pd.DataFrame) -> dict:
        sig = fn(df)
        if not (sig.get("buy") or sig.get("sell")):
            return sig
        regime = detect_regime(df, ema_period=ema_period, slope_threshold=slope_threshold)
        if regime != "range":
            return {**sig, "buy": False, "sell": False, "suppressed": "non-range"}
        return sig
    return wrapped


def with_trend(fn: SignalFn, *, ema_period: int = 50, slope_threshold: float = 0.0008) -> SignalFn:
    """Momentum/breakout: keep only the signal aligned with the trend direction."""
    def wrapped(df: pd.DataFrame) -> dict:
        sig = fn(df)
        if not (sig.get("buy") or sig.get("sell")):
            return sig
        regime = detect_regime(df, ema_period=ema_period, slope_threshold=slope_threshold)
        if regime == "up":
            return {**sig, "sell": False}       # only longs in an up-trend
        if regime == "down":
            return {**sig, "buy": False}        # only shorts in a down-trend
        return {**sig, "buy": False, "sell": False, "suppressed": "range"}
    return wrapped
