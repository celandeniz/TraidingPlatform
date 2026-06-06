"""Scanner — score & rank the whole universe on a 5-minute cadence.

Pulls recent bars for every symbol (batched via the provider), scores each with
the transparent buy-edge model, and returns the top-N ranked candidates. Designed
for periodic scanning (hundreds of symbols), NOT live per-symbol streaming.

Results are a ranked list of estimated-edge scores — explicitly NOT profit
guarantees. The runner/web layer decides what to do with them (list, and/or feed
the guarded auto-trader).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .score import score_symbol


@dataclass
class ScanResult:
    timeframe: str
    scanned: int
    candidates: list = field(default_factory=list)   # list[dict] ranked desc by score
    skipped: int = 0
    error: str = ""


class Scanner:
    def __init__(self, provider, cfg: Optional[dict] = None):
        self._provider = provider
        self._cfg = cfg or {}

    def _bars_for(self, symbols: list[str], timeframe: str, lookback: int) -> dict:
        # Prefer a batched multi-symbol pull; fall back to per-symbol if absent.
        multi = getattr(self._provider, "get_recent_bars_multi", None)
        if callable(multi):
            return multi(symbols, timeframe, lookback)
        out = {}
        for s in symbols:
            try:
                df = self._provider.get_recent_bars(s, timeframe, lookback)
                if df is not None and not df.empty:
                    out[s] = df
            except Exception:  # noqa: BLE001 - one bad symbol shouldn't sink the scan
                continue
        return out

    def scan(self, symbols: list[str], *, timeframe: str = "5m", lookback: int = 60,
             top_n: int = 25, min_score: float = 0.0,
             weights: Optional[dict] = None) -> ScanResult:
        if not symbols:
            return ScanResult(timeframe=timeframe, scanned=0, error="empty universe")
        bars = self._bars_for(symbols, timeframe, lookback)
        scored, skipped = [], 0
        for sym in symbols:
            df = bars.get(sym)
            if df is None:
                skipped += 1
                continue
            res = score_symbol(sym, df, weights=weights)
            if res.error:
                skipped += 1
                continue
            scored.append(res)
        scored.sort(key=lambda r: r.score, reverse=True)
        ranked = [r.as_dict() for r in scored if r.score >= min_score][:top_n]
        return ScanResult(timeframe=timeframe, scanned=len(symbols),
                          candidates=ranked, skipped=skipped)
