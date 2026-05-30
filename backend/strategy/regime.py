"""Trend regime classification (shared helper, not a strategy in Phase 1).

Logged alongside each signal; no suppression yet (that is the Phase 2 decision
layer's job). Classifies the latest bar as up / down / range from EMA slope.
"""
from __future__ import annotations

import pandas as pd

from .indicators import ema


def detect(
    df: pd.DataFrame, *, ema_period: int = 50, slope_threshold: float = 0.0005
) -> str:
    """Return "up" | "down" | "range" for the last bar.

    slope = (EMA[-1] - EMA[-2]) / price, normalised so the threshold is scale-free.
    |slope| < slope_threshold => "range".
    """
    close = df["close"]
    e = ema(close, ema_period)
    if len(e) < 2 or pd.isna(e.iloc[-1]) or pd.isna(e.iloc[-2]):
        return "range"
    price = close.iloc[-1]
    if price == 0 or pd.isna(price):
        return "range"
    slope = (e.iloc[-1] - e.iloc[-2]) / price
    if abs(slope) < slope_threshold:
        return "range"
    return "up" if slope > 0 else "down"
