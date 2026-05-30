"""News + earnings adapter (provider-agnostic seam).

Phase 2 uses Alpaca's News API (free with the existing account). Returns recent
headlines per symbol with timestamps so the catalyst gate can reason about news
recency. Earnings-calendar support is best-effort: Alpaca's free tier does not
expose a clean earnings calendar, so `earnings_in_days` returns None unless a
provider is wired in later — callers treat None as "unknown".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class Headline:
    symbol: str
    headline: str
    summary: str
    created_at: datetime
    url: str = ""

    def age_minutes(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.created_at).total_seconds() / 60.0


class AlpacaNewsProvider:
    def __init__(self, api_key: str, api_secret: str):
        # Imported lazily so the rest of the system loads even if the news client
        # is unavailable in a given alpaca-py version.
        from alpaca.data.historical.news import NewsClient

        self._client = NewsClient(api_key, api_secret)

    def recent_headlines(self, symbol: str, lookback_hours: int = 24, limit: int = 10) -> list[Headline]:
        from alpaca.data.requests import NewsRequest

        start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        req = NewsRequest(symbols=symbol, start=start, limit=limit, include_content=False)
        try:
            resp = self._client.get_news(req)
        except Exception:
            return []
        items = getattr(resp, "data", None)
        raw = items.get("news", []) if isinstance(items, dict) else getattr(resp, "news", [])
        out: list[Headline] = []
        for n in raw:
            created = getattr(n, "created_at", None) or getattr(n, "updated_at", None)
            if created is None:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            out.append(
                Headline(
                    symbol=symbol,
                    headline=getattr(n, "headline", "") or "",
                    summary=getattr(n, "summary", "") or "",
                    created_at=created,
                    url=getattr(n, "url", "") or "",
                )
            )
        return out

    def earnings_in_days(self, symbol: str) -> Optional[int]:
        """Best-effort. Free Alpaca tier lacks a clean earnings calendar -> unknown."""
        return None
