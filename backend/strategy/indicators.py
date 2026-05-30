"""Pure technical indicators. No I/O, no state — easy to unit test.

Every function takes pandas objects and returns pandas objects, so they compose
and can be verified against hand-computed values.
"""
from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # When there is no loss at all, RSI is 100 by definition.
    out = out.where(avg_loss != 0, 100.0)
    return out


def zscore(series: pd.Series, window: int) -> pd.Series:
    """Rolling z-score of a series."""
    mean = series.rolling(window).mean()
    std = series.rolling(window).std()
    return (series - mean) / std


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-agnostic cumulative VWAP from typical price * volume.

    Expects columns: high, low, close, volume.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_pv = (typical * df["volume"]).cumsum()
    return cum_pv / cum_vol


def bollinger(
    close: pd.Series, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (mid, upper, lower) Bollinger Bands.

    mid = SMA(period); upper/lower = mid +/- std * rolling_std(period).
    Uses population std (ddof=0), the convention for Bollinger Bands.
    """
    mid = close.rolling(period).mean()
    dev = close.rolling(period).std(ddof=0)
    upper = mid + std * dev
    lower = mid - std * dev
    return mid, upper, lower
