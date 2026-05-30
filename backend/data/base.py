"""DataProvider interface — the seam that keeps the engine broker-agnostic.

Phase 1 needs streaming 1m bars + historical bar pulls (warmup and multi-TF
Bollinger). Phase 3's execution adapter will sit behind a sibling interface so
paper -> live is a config switch, not a rewrite.
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol

import pandas as pd

# Called with (symbol, bar_dict) on each closed bar.
BarHandler = Callable[[str, dict], Awaitable[None]]


class DataProvider(Protocol):
    async def stream_bars(self, symbols: list[str], handler: BarHandler) -> None:
        """Subscribe to closed bars and invoke handler for each."""
        ...

    def get_recent_bars(
        self, symbol: str, timeframe: str, lookback: int
    ) -> pd.DataFrame:
        """Return the most recent `lookback` bars, oldest..newest.

        Columns: open, high, low, close, volume; tz-aware UTC index.
        timeframe examples: "1m", "3m", "5m", "15m", "45m", "1h".
        """
        ...
