"""StrategyBrief — the normalized natural-language request."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyBrief:
    text: str                       # the user's NL strategy description
    symbol: str = "AAPL"
    timeframe: str = "1d"
    bars: int = 750                 # history to backtest over
    n_candidates: int = 4           # best-of-N

    @classmethod
    def from_request(cls, text: str, *, symbol: str = "AAPL", timeframe: str = "1d",
                     bars: int = 750, n_candidates: int = 4) -> "StrategyBrief":
        if not text or not text.strip():
            raise ValueError("brief text is required")
        return cls(text=text.strip(), symbol=symbol.upper(), timeframe=timeframe,
                   bars=max(120, int(bars)), n_candidates=max(1, min(8, int(n_candidates))))
