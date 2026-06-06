"""MarketDataProvider protocol — the research-data seam.

Mirrors the live-bar ``DataProvider`` (backend/data/base.py) for OHLCV, then adds
the research surface OpenAlice exposes (fundamentals, estimates, earnings,
insider trades, movers, cross-asset search). Implementations keep heavy imports
lazy so importing this module is free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol

import pandas as pd

AssetKind = Literal["equity", "crypto", "currency", "commodity", "index", "macro"]


@dataclass
class SymbolMatch:
    symbol: str
    name: str = ""
    kind: AssetKind = "equity"
    exchange: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Fundamentals:
    """A flattened snapshot of a company's profile + key ratios.

    Fields are best-effort: providers differ, so any value may be None.
    """

    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    raw: dict = field(default_factory=dict)  # full provider payload for power users


class MarketDataProvider(Protocol):
    def get_recent_bars(
        self, symbol: str, timeframe: str = "1d", lookback: int = 250,
        kind: AssetKind = "equity",
    ) -> pd.DataFrame:
        """OHLCV bars, oldest..newest. Columns: open, high, low, close, volume."""
        ...

    def search_symbols(self, query: str, kind: Optional[AssetKind] = None) -> list[SymbolMatch]:
        """Cross-asset symbol search."""
        ...

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        """Company profile + key ratios (equities)."""
        ...

    def get_earnings_calendar(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        """Upcoming/period earnings events."""
        ...

    def get_insider_trading(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        """Recent insider transactions for a symbol."""
        ...

    def get_market_movers(self, kind: Literal["gainers", "losers", "active"] = "gainers") -> pd.DataFrame:
        """Market movers / discovery."""
        ...
