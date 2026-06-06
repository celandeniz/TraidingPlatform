"""Yahoo Finance MarketDataProvider via the `yfinance` package (free, no API key).

Implements the same MarketDataProvider seam as the OpenBB provider — bars,
fundamentals, search, earnings, insider, movers — plus ``get_news`` (Yahoo carries
per-ticker headlines the news aggregator consumes). ``yfinance`` is imported
lazily, so this module is free to import and only pulls the dependency when a call
is actually made. Every method is defensive: a Yahoo hiccup degrades to an empty
frame / sparse object rather than raising into the caller.

Clean-room: written against the public yfinance API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd

from .base import AssetKind, Fundamentals, SymbolMatch
from ..research.news_provider import Headline

# Our timeframe tokens -> yfinance intervals (3m/45m have no native yfinance bar).
_INTERVAL = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h",
             "1d": "1d", "1wk": "1wk", "1mo": "1mo"}
# yfinance caps intraday history: 1m ~7d, others ~60d. Pick a safe period.
_PERIOD_FOR = {"1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "1h": "3mo",
               "1d": "1y", "1wk": "5y", "1mo": "max"}


class YahooProvider:
    def __init__(self):
        self._yf = None

    def _client(self):
        if self._yf is None:
            import yfinance as yf  # lazy: only when Yahoo data is actually used

            self._yf = yf
        return self._yf

    def get_recent_bars(self, symbol: str, timeframe: str = "1d", lookback: int = 250,
                        kind: AssetKind = "equity") -> pd.DataFrame:
        yf = self._client()
        interval = _INTERVAL.get(timeframe, timeframe)
        period = _PERIOD_FOR.get(interval, "1mo")
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval,
                                           auto_adjust=False)
        except Exception:  # noqa: BLE001
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if df.empty:
            return df
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                "Close": "close", "Volume": "volume"})
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        return df[keep].tail(lookback)

    def search_symbols(self, query: str, kind: Optional[AssetKind] = None) -> list[SymbolMatch]:
        yf = self._client()
        try:
            results = yf.Search(query, max_results=10).quotes
        except Exception:  # noqa: BLE001 - older yfinance has no Search
            return []
        out: list[SymbolMatch] = []
        for q in results or []:
            sym = q.get("symbol")
            if not sym:
                continue
            out.append(SymbolMatch(
                symbol=sym, name=q.get("shortname") or q.get("longname") or "",
                kind=kind or "equity", exchange=q.get("exchange") or "", extra=q))
        return out

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        yf = self._client()
        f = Fundamentals(symbol=symbol)
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception:  # noqa: BLE001
            return f
        f.name = info.get("longName") or info.get("shortName")
        f.sector = info.get("sector")
        f.industry = info.get("industry")
        f.market_cap = _num(info.get("marketCap"))
        f.pe_ratio = _num(info.get("trailingPE"))
        f.debt_to_equity = _num(info.get("debtToEquity"))
        f.profit_margin = _num(info.get("profitMargins"))
        f.raw = info
        return f

    def get_earnings_calendar(self, start: Optional[str] = None,
                              end: Optional[str] = None) -> pd.DataFrame:
        # Yahoo exposes earnings per-ticker, not a market-wide calendar.
        return pd.DataFrame()

    def get_insider_trading(self, symbol: str, limit: int = 100) -> pd.DataFrame:
        yf = self._client()
        try:
            df = yf.Ticker(symbol).insider_transactions
            return df.head(limit) if df is not None else pd.DataFrame()
        except Exception:  # noqa: BLE001
            return pd.DataFrame()

    def get_market_movers(self, kind: Literal["gainers", "losers", "active"] = "gainers") -> pd.DataFrame:
        yf = self._client()
        screen = {"gainers": "day_gainers", "losers": "day_losers",
                  "active": "most_actives"}.get(kind, "day_gainers")
        try:
            res = yf.screen(screen)
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
            return pd.json_normalize(quotes)
        except Exception:  # noqa: BLE001 - screen API varies by yfinance version
            return pd.DataFrame()

    def get_news(self, symbol: str, limit: int = 20) -> list[Headline]:
        """Per-ticker Yahoo Finance headlines as shared Headline objects."""
        yf = self._client()
        try:
            items = yf.Ticker(symbol).news or []
        except Exception:  # noqa: BLE001
            return []
        out: list[Headline] = []
        for n in items[:limit]:
            # yfinance returns either flat dicts or {"content": {...}} per version
            c = n.get("content", n)
            title = c.get("title") or n.get("title") or ""
            if not title:
                continue
            ts = n.get("providerPublishTime")
            created = (datetime.fromtimestamp(ts, tz=timezone.utc) if ts
                       else datetime.now(timezone.utc))
            url = (c.get("canonicalUrl", {}) or {}).get("url") or n.get("link", "") or ""
            out.append(Headline(symbol=symbol, headline=title,
                                summary=c.get("summary", "") or "", created_at=created,
                                url=url))
        return out


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
