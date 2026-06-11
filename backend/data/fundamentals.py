"""Fundamentals provider — compact metric subset for the persona panel.

yfinance Ticker.info backed, JSON-cached per symbol with a TTL. Fetch is
pluggable (tests inject fakes; no network in tests). On fetch failure raises
FundamentalsUnavailable so callers degrade explicitly (spec: personas vote
low-confidence pass) instead of judging on partial data.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

FetchFn = Callable[[str], dict]

# Whitelist (spec: <=15 metrics + 52w range). Anything else is dropped.
METRIC_KEYS = [
    "trailingPE", "forwardPE", "pegRatio", "priceToBook", "returnOnEquity",
    "profitMargins", "operatingMargins", "debtToEquity", "freeCashflow",
    "revenueGrowth", "earningsGrowth", "marketCap", "dividendYield", "beta",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
]


class FundamentalsUnavailable(RuntimeError):
    pass


def _fetch_yfinance(symbol: str) -> dict:
    import yfinance as yf

    info = yf.Ticker(symbol).info
    if not info:
        return {}
    return dict(info)


class FundamentalsProvider:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None,
                 *, ttl_hours: float = 24.0):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or _fetch_yfinance
        self.ttl_seconds = ttl_hours * 3600.0

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}_fundamentals.json"

    def get(self, symbol: str) -> dict:
        """Whitelisted metrics for one symbol; cached for ttl_hours."""
        p = self._path(symbol)
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if time.time() - float(data.get("fetched_at", 0)) < self.ttl_seconds:
                    return data["metrics"]
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # corrupt cache -> refetch
        try:
            raw = self.fetch_fn(symbol)
        except Exception as exc:  # noqa: BLE001 — converted to a typed failure
            raise FundamentalsUnavailable(f"{symbol}: {exc}") from exc
        metrics = {k: raw[k] for k in METRIC_KEYS if raw.get(k) is not None}
        p.write_text(json.dumps({"fetched_at": time.time(), "metrics": metrics}))
        return metrics
