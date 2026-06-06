"""FastMCP server exposing the platform to external agents (Claude Code, etc.).

Thin wrapper: builds a Toolset from config and registers each method as an MCP
tool. Run it over stdio with:

    python -m backend.mcp.server

Requires the MCP SDK (``pip install mcp``); the import is deferred so the rest of
the package loads without it. Order submission routes through the OMS so every
agent action is auditable; market-data tools are live only when marketdata.enabled.
"""
from __future__ import annotations

from .tools import Toolset


def build_toolset() -> Toolset:
    """Assemble a Toolset wired to the configured executor, OMS, and market data."""
    from ..brokers import build_routing_executor
    from ..marketdata import build_market_data_provider
    from ..oms.ledger import OrderManager
    from ..portfolio.guards import build_guard_pipeline
    from ..settings import get_config, get_settings

    settings = get_settings()
    config = get_config()
    executor = build_routing_executor(settings, config)
    executor = build_guard_pipeline(executor, config)  # no-op unless guards.enabled
    oms = OrderManager(executor)
    market_data = build_market_data_provider(settings, config)  # None unless enabled
    return Toolset(executor, oms=oms, market_data=market_data, config=config)


def build_server(toolset: Toolset | None = None):
    """Create a FastMCP server with every Toolset method registered as a tool."""
    from mcp.server.fastmcp import FastMCP  # lazy: requires the mcp package

    ts = toolset or build_toolset()
    mcp = FastMCP("TraidingPlatform")

    @mcp.tool()
    def list_positions() -> dict:
        """Current open positions across all configured brokers."""
        return ts.list_positions()

    @mcp.tool()
    def account_summary() -> dict:
        """Account equity, cash, and buying power."""
        return ts.account_summary()

    @mcp.tool()
    def submit_order(symbol: str, side: str, qty: float, reduce_only: bool = False,
                     message: str = "via MCP") -> dict:
        """Submit a market order (auditable via the order ledger). side: buy|sell."""
        return ts.submit_order(symbol, side, qty, reduce_only=reduce_only, message=message)

    @mcp.tool()
    def order_history(limit: int = 50) -> dict:
        """Recent orders and their stage->commit->push->fill history."""
        return ts.order_history(limit=limit)

    @mcp.tool()
    def recent_signals(limit: int = 20) -> dict:
        """Most recent strategy signals from the signal tape."""
        return ts.recent_signals(limit=limit)

    @mcp.tool()
    def get_market_data(symbol: str, timeframe: str = "1d", bars: int = 100,
                        kind: str = "equity") -> dict:
        """OHLCV bars for a symbol (equity|crypto|currency|index)."""
        return ts.get_market_data(symbol, timeframe, bars, kind=kind)

    @mcp.tool()
    def get_fundamentals(symbol: str) -> dict:
        """Company profile + key ratios for an equity symbol."""
        return ts.get_fundamentals(symbol)

    @mcp.tool()
    def search_symbols(query: str) -> dict:
        """Cross-asset symbol search."""
        return ts.search_symbols(query)

    @mcp.tool()
    def run_backtest(symbol: str, timeframe: str = "5m", strategy: str = "spike_fade",
                     bars: int = 2000) -> dict:
        """Run one no-lookahead backtest. strategy: spike_fade|ema_momentum|donchian."""
        return ts.run_backtest(symbol, timeframe, strategy, bars)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
