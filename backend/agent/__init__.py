"""Autonomous agent layer — LLM-driven actions over the MCP toolset, gated.

The auto-trader proposes (and optionally executes) trades by asking an LLM to
reason over live context, then routing any action through the SAME OMS + guard +
risk pipeline a human uses. Dry-run by default, hard-capped, fully logged.
"""
from .auto_trader import AutoTrader, DECISION_SCHEMA

__all__ = ["AutoTrader", "DECISION_SCHEMA"]
