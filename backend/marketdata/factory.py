"""Build a MarketDataProvider from config.yaml.

Reads the ``marketdata:`` namespace. Off by default — returns None unless
``marketdata.enabled`` is true, so the runner/dashboard only construct it when
the research surface is actually wanted.
"""
from __future__ import annotations

from typing import Optional

from .base import MarketDataProvider


def build_market_data_provider(settings, cfg: dict) -> Optional[MarketDataProvider]:
    md = cfg.get("marketdata", {}) or {}
    if not md.get("enabled"):
        return None
    backend = md.get("backend", "openbb")
    if backend == "yahoo":
        from .yahoo_provider import YahooProvider

        return YahooProvider()
    if backend == "openbb":
        from .openbb_provider import OpenBBProvider

        # API keys may live in .env (settings) or inline in config.yaml.
        api_keys = dict(md.get("api_keys", {}) or {})
        for name in ("fmp_api_key", "polygon_api_key", "intrinio_api_key",
                     "tiingo_token", "alpha_vantage_api_key"):
            val = getattr(settings, name, "")
            if val:
                api_keys[name] = val
        return OpenBBProvider(providers=md.get("providers", {}), api_keys=api_keys)
    raise ValueError(f"unknown marketdata backend: {backend}")
