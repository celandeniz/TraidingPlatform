"""Unified news — one searchable view over every news source we have.

Merges headlines from any combination of: Alpaca News (per-symbol, needs keys),
RSS feeds (market-wide archive), and Yahoo Finance (per-symbol, free). Each source
is optional and queried defensively; results are de-duplicated (by url/title) and
sorted newest-first so the caller gets one clean, ranked stream regardless of
which sources are configured.

Reuses the shared ``Headline`` dataclass so the catalyst gate / dashboard consume
every source identically.
"""
from __future__ import annotations

from typing import Optional

from .news_provider import Headline


class UnifiedNews:
    def __init__(self, *, alpaca=None, rss=None, yahoo=None):
        # alpaca: AlpacaNewsProvider | None  (recent_headlines(symbol))
        # rss:    RssNewsAggregator   | None  (fetch()/search())
        # yahoo:  YahooProvider       | None  (get_news(symbol))
        self._alpaca = alpaca
        self._rss = rss
        self._yahoo = yahoo

    def sources(self) -> list[str]:
        names = []
        if self._alpaca is not None:
            names.append("alpaca")
        if self._rss is not None:
            names.append("rss")
        if self._yahoo is not None:
            names.append("yahoo")
        return names

    def latest(self, symbol: Optional[str] = None, limit: int = 30) -> list[Headline]:
        """Newest headlines across all sources, de-duplicated and ranked.

        With a symbol, queries the per-symbol sources (Alpaca, Yahoo); without one,
        leans on the market-wide RSS archive. RSS is always included when present.
        """
        collected: list[Headline] = []
        if symbol:
            sym = symbol.upper()
            collected += self._safe(lambda: self._alpaca.recent_headlines(sym, limit=limit)
                                    if self._alpaca else [])
            collected += self._safe(lambda: self._yahoo.get_news(sym, limit=limit)
                                    if self._yahoo else [])
        if self._rss is not None:
            collected += self._safe(lambda: self._rss._read_archive())
        return _dedup_sorted(collected)[:limit]

    def search(self, keyword: str, symbol: Optional[str] = None, limit: int = 50) -> list[Headline]:
        """Keyword search. RSS is market-wide; Alpaca/Yahoo are per-symbol, so pass
        ``symbol`` to include them (otherwise only the RSS archive is searched)."""
        kw = keyword.lower().strip()
        if not kw:
            return []
        hits: list[Headline] = []
        if self._rss is not None:
            hits += self._safe(lambda: self._rss.search(keyword, limit=limit))
        # scan the merged stream (incl. per-symbol sources when a symbol is given)
        pool = self.latest(symbol=symbol, limit=limit * 2)
        hits += [h for h in pool
                 if kw in h.headline.lower() or kw in (h.summary or "").lower()]
        return _dedup_sorted(hits)[:limit]

    @staticmethod
    def _safe(fn) -> list:
        try:
            return list(fn() or [])
        except Exception:  # noqa: BLE001 - one bad source never sinks the rest
            return []


def _dedup_sorted(items: list[Headline]) -> list[Headline]:
    seen = set()
    out = []
    for h in items:
        key = (h.url or "").strip() or h.headline.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(h)
    out.sort(key=lambda h: h.created_at, reverse=True)
    return out
