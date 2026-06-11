"""Persona panel — orchestrates the legend personas into one cached verdict.

Pure pieces (consensus, build_context, price_summary) are separated from the
I/O orchestrator (PersonaPanel) so the math is exhaustively testable. The
panel NEVER fails because fundamentals are missing — it degrades the context
and lets the personas vote pass (spec: Error handling).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from backend.data.fundamentals import FundamentalsUnavailable
from .base import PersonaVote
from .personas.legends import build_legend_personas

VERDICT_THRESHOLD = 0.15
_DIR = {"long": 1.0, "short": -1.0, "pass": 0.0}


@dataclass
class PanelResult:
    symbol: str
    verdict: str
    score: float
    votes: list = field(default_factory=list)      # list[PersonaVote]
    fundamentals_available: bool = True
    generated_at: str = ""
    cached: bool = False


def consensus(votes: list, weights: Optional[dict] = None) -> "tuple[str, float]":
    """Weighted directional score in [-1, 1] -> verdict via +/-0.15 threshold."""
    weights = weights or {}
    total_w = sum(weights.get(v.name, 1.0) for v in votes)
    if total_w <= 0 or not votes:
        return "pass", 0.0
    score = sum(weights.get(v.name, 1.0) * _DIR[v.side] * v.confidence
                for v in votes) / total_w
    if score >= VERDICT_THRESHOLD:
        return "long", round(score, 4)
    if score <= -VERDICT_THRESHOLD:
        return "short", round(score, 4)
    return "pass", round(score, 4)


def price_summary(df: Optional[pd.DataFrame]) -> Optional[dict]:
    """1y return / annualized vol / distance from 52w extremes, from daily bars."""
    if df is None or len(df) < 60:
        return None
    close = df["close"].iloc[-252:]
    rets = close.pct_change().dropna()
    last = float(close.iloc[-1])
    hi, lo = float(close.max()), float(close.min())
    return {
        "return_1y_pct": round((last / float(close.iloc[0]) - 1.0) * 100.0, 2),
        "vol_ann_pct": round(float(rets.std()) * (252 ** 0.5) * 100.0, 2),
        "off_52w_high_pct": round((last / hi - 1.0) * 100.0, 2),
        "off_52w_low_pct": round((last / lo - 1.0) * 100.0, 2),
    }


def build_context(fundamentals: Optional[dict], price: Optional[dict],
                  headlines: list) -> "tuple[str, bool]":
    """One compact context string for every persona. Returns (text, available)."""
    lines = []
    available = bool(fundamentals)
    if fundamentals:
        lines.append("Fundamentals: " + "; ".join(
            f"{k}: {v}" for k, v in fundamentals.items()))
    else:
        lines.append("fundamentals: unavailable")
    if price:
        lines.append("Price (1y): " + "; ".join(
            f"{k}: {v}" for k, v in price.items()))
    else:
        lines.append("price summary: unavailable")
    if headlines:
        lines.append("Recent headlines: " + " | ".join(headlines[:5]))
    return "\n".join(lines), available


class PersonaPanel:
    def __init__(self, client, fundamentals_provider, *, cache_dir: "Path | str",
                 daily_bars_fn: "Callable[[str], Optional[pd.DataFrame]]",
                 headlines_fn: "Callable[[str], list]",
                 ttl_hours: float = 24.0, weights: Optional[dict] = None):
        self._client = client
        self._fund = fundamentals_provider
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._daily_bars_fn = daily_bars_fn
        self._headlines_fn = headlines_fn
        self.ttl_seconds = ttl_hours * 3600.0
        self.weights = weights or {}

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}_panel.json"

    def run(self, symbol: str, *, refresh: bool = False) -> PanelResult:
        p = self._path(symbol)
        if not refresh and p.exists():
            try:
                data = json.loads(p.read_text())
                if time.time() - float(data.get("saved_at", 0)) < self.ttl_seconds:
                    res = PanelResult(**data["result"])
                    res.votes = [PersonaVote(**v) for v in res.votes]
                    res.cached = True
                    return res
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass  # corrupt cache -> recompute

        try:
            fundamentals = self._fund.get(symbol)
        except FundamentalsUnavailable:
            fundamentals = None
        try:
            price = price_summary(self._daily_bars_fn(symbol))
        except Exception:  # noqa: BLE001 — price summary is best-effort
            price = None
        try:
            headlines = self._headlines_fn(symbol) or []
        except Exception:  # noqa: BLE001 — headlines are best-effort
            headlines = []

        context, available = build_context(fundamentals, price, headlines)
        votes = [persona.analyze(symbol, context)
                 for persona in build_legend_personas(self._client)]
        verdict, score = consensus(votes, self.weights)
        result = PanelResult(
            symbol=symbol.upper(), verdict=verdict, score=score, votes=votes,
            fundamentals_available=available,
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"), cached=False,
        )
        payload = asdict(result)
        p.write_text(json.dumps({"saved_at": time.time(), "result": payload}))
        return result
