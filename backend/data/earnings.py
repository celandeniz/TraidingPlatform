"""Earnings calendar provider — yfinance-backed, JSON-cached per symbol.

Spec rule: on fetch failure raise EarningsUnavailable so earnings_drift reports
"data unavailable" instead of trading on partial data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

FetchFn = Callable[[str], list]


class EarningsUnavailable(RuntimeError):
    pass


def _fetch_yfinance(symbol: str) -> list:
    import yfinance as yf

    df = yf.Ticker(symbol).get_earnings_dates(limit=40)
    if df is None or df.empty:
        return []
    return [pd.Timestamp(ts).tz_localize(None).normalize() for ts in df.index]


class EarningsCalendar:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or _fetch_yfinance

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}_earnings.json"

    def get_dates(self, symbol: str) -> list[pd.Timestamp]:
        """Past + scheduled earnings dates (naive, normalized), oldest..newest."""
        p = self._path(symbol)
        if p.exists():
            iso = json.loads(p.read_text())
            return [pd.Timestamp(s) for s in iso]
        try:
            dates = sorted(pd.Timestamp(d).tz_localize(None).normalize()
                           if pd.Timestamp(d).tzinfo else pd.Timestamp(d).normalize()
                           for d in self.fetch_fn(symbol))
        except Exception as exc:  # noqa: BLE001 — converted to a typed failure
            raise EarningsUnavailable(f"{symbol}: {exc}") from exc
        p.write_text(json.dumps([d.date().isoformat() for d in dates]))
        return dates
