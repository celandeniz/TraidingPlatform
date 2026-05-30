"""On-demand 'why is it moving?' co-pilot (Claude, cached per symbol).

Triggered by a dashboard click, never on the hot path. Summarises recent Alpaca
headlines + the price move into 2-3 sentences and a catalyst tag. (Web search can
be added later; v1 grounds the answer in the headlines we already fetch, which is
more reliable than free-form generation.)
"""
from __future__ import annotations

from .base import ResearchContext
from .llm import ClaudeClient
from .news_provider import AlpacaNewsProvider

_SYSTEM = (
    "You explain why a US stock is moving intraday, for a trader deciding whether to "
    "fade the move. You are given recent headlines and the price change. In 2-3 "
    "sentences, explain the most likely driver and classify the catalyst. If the "
    "headlines do not explain the move, say it looks technical/flow-driven and tag "
    "'none'. Do not invent news. Not investment advice."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentence explanation"},
        "tag": {"type": "string", "enum": ["earnings", "news", "macro", "none"]},
    },
    "required": ["summary", "tag"],
}


class CopilotAgent:
    def __init__(self, client: ClaudeClient, news: AlpacaNewsProvider, cache_minutes: int = 10):
        self._client = client
        self._news = news
        self._cache_minutes = cache_minutes
        self._cache: dict[str, tuple[float, ResearchContext]] = {}

    def explain(self, symbol: str, *, change_pct: float | None = None, clock=None) -> ResearchContext:
        import time as _t

        now = (clock or _t.monotonic)()
        hit = self._cache.get(symbol)
        if hit and (now - hit[0]) < self._cache_minutes * 60:
            return hit[1]

        headlines = self._news.recent_headlines(symbol, lookback_hours=24, limit=5)
        hl_text = "\n".join(f"- {h.headline}" for h in headlines) or "(no recent headlines)"
        move = f"{change_pct:+.2f}%" if change_pct is not None else "n/a"
        user = f"Symbol: {symbol}\nPrice change today: {move}\nRecent headlines:\n{hl_text}\n"

        try:
            out = self._client.structured(
                system=_SYSTEM, user=user,
                tool_name="why_moving", tool_schema=_SCHEMA, max_tokens=300,
            )
            ctx = ResearchContext(
                symbol=symbol,
                summary=str(out.get("summary", "")),
                tag=str(out.get("tag", "none")),
                headlines=[h.headline for h in headlines[:3]],
            )
        except Exception as exc:
            ctx = ResearchContext(
                symbol=symbol,
                summary=f"Co-pilot unavailable: {exc}",
                tag="none",
                headlines=[h.headline for h in headlines[:3]],
            )

        self._cache[symbol] = (now, ctx)
        return ctx
