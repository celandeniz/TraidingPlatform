"""Cross-asset market-data layer.

Extends the platform beyond live trading bars (Alpaca/ccxt) to research-grade
data: fundamentals, estimates, earnings calendars, insider trades, movers, and
cross-asset symbol search across equities/crypto/commodities/forex/macro.

The default backend wraps the upstream OpenBB Python SDK (permissively licensed);
nothing here is ported from OpenAlice. Off by default — only constructed when
``marketdata.enabled`` is set in config.yaml.
"""
from .base import Fundamentals, MarketDataProvider, SymbolMatch
from .factory import build_market_data_provider

__all__ = [
    "MarketDataProvider",
    "Fundamentals",
    "SymbolMatch",
    "build_market_data_provider",
]
