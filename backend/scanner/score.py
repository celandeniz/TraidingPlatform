"""Transparent buy-edge score for one symbol — pure, deterministic, explainable.

Blends four 0..1 components into a 0-100 score (long/"buy" bias):
  * trend   — fast EMA above slow EMA (soft, scaled by separation)
  * momentum— recent N-bar return, squashed
  * rsi_room— prefers RSI rising but with room to run (penalize overbought)
  * regime  — EMA(50)-slope regime: up favors longs, down penalizes

This is an ESTIMATED EDGE, not a probability of profit. The components dict is
returned so the ranking is fully explainable. No network, no lookahead (uses only
the bars given).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

DEFAULT_WEIGHTS = {"trend": 0.30, "momentum": 0.30, "rsi_room": 0.20, "regime": 0.20}


@dataclass
class ScoreResult:
    symbol: str
    score: float                 # 0..100 (estimated edge, NOT a win probability)
    side: str = "buy"
    last: float = 0.0
    momentum_pct: float = 0.0
    rsi: float = 50.0
    regime: str = "range"
    components: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "score": round(self.score, 1), "side": self.side,
                "last": round(self.last, 4), "momentum_pct": round(self.momentum_pct, 3),
                "rsi": round(self.rsi, 1), "regime": self.regime,
                "components": {k: round(v, 3) for k, v in self.components.items()},
                "error": self.error}


def _ema(values, period: int):
    k = 2.0 / (period + 1)
    e = values[0]
    out = [e]
    for v in values[1:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _rsi(values, period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        ch = values[i] - values[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def score_symbol(symbol: str, df: pd.DataFrame, *, weights: Optional[dict] = None,
                 momentum_bars: int = 12, regime_slope_threshold: float = 0.0002) -> ScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    if df is None or len(df) < 30 or "close" not in df:
        return ScoreResult(symbol=symbol, score=0.0, error="insufficient data")
    close = [float(x) for x in df["close"].tolist()]
    last = close[-1]

    ema_fast = _ema(close, 12)[-1]
    ema_slow = _ema(close, 26)[-1]
    sep = (ema_fast - ema_slow) / last if last else 0.0
    c_trend = 1.0 / (1.0 + math.exp(-sep * 800))           # soft step around 0

    n = min(momentum_bars, len(close) - 1)
    mom = (last / close[-1 - n] - 1.0) if close[-1 - n] else 0.0
    c_mom = 0.5 * (1.0 + math.tanh(mom * 40))               # squash to 0..1

    rsi = _rsi(close, 14)
    # reward RSI ~45-65 (room to run), penalize overbought >72 and weak <35
    c_rsi = max(0.0, 1.0 - abs(rsi - 57.0) / 35.0)

    ema50 = _ema(close, 50)
    slope = (ema50[-1] - ema50[-2]) / last if last and len(ema50) >= 2 else 0.0
    if abs(slope) < regime_slope_threshold:
        regime, c_regime = "range", 0.5
    elif slope > 0:
        regime, c_regime = "up", 1.0
    else:
        regime, c_regime = "down", 0.0

    comps = {"trend": c_trend, "momentum": c_mom, "rsi_room": c_rsi, "regime": c_regime}
    total_w = sum(w.get(k, 0.0) for k in comps) or 1.0
    score = 100.0 * sum(w.get(k, 0.0) * v for k, v in comps.items()) / total_w

    return ScoreResult(symbol=symbol, score=score, side="buy", last=last,
                       momentum_pct=mom * 100.0, rsi=rsi, regime=regime, components=comps)
