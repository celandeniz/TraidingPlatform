"""Fundamental tilt score via Claude (daily-cached).

Alpaca's free tier has shallow fundamentals, so this is best-effort: we give Claude
the symbol and recent price context and ask for a fundamental tilt based on its
knowledge, with an explicit honesty flag that this is not real-time filing data.
The result is a confirmation dimension (-1..+1), not a hard gate by default.
"""
from __future__ import annotations

from .base import FundamentalScore
from .llm import ClaudeClient

_SYSTEM = (
    "You are a disciplined equity analyst. Given a US mega-cap stock and brief price "
    "context, output a FUNDAMENTAL TILT for a SHORT-TERM trade: +1 = fundamentals "
    "strongly support being long, -1 = strongly support being short/avoiding longs, "
    "0 = neutral/unknown. Base it on durable fundamentals you know (margins, growth, "
    "competitive position, valuation), NOT on the recent price move. Be conservative: "
    "if you are unsure or lack recent data, return a score near 0 and say so. You are "
    "not giving investment advice."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "description": "fundamental tilt, -1..+1"},
        "label": {"type": "string", "description": "1-3 word label, e.g. 'quality/expensive'"},
        "rationale": {"type": "string", "description": "<=2 sentences, cite the driver"},
    },
    "required": ["score", "label", "rationale"],
}


class FundamentalAgent:
    def __init__(self, client: ClaudeClient, cache_hours: int = 24):
        self._client = client
        self._cache_hours = cache_hours
        self._cache: dict[str, tuple[float, FundamentalScore]] = {}

    def score(self, symbol: str, *, price_context: str = "", clock=None) -> FundamentalScore:
        import time as _t

        now = (clock or _t.monotonic)()
        hit = self._cache.get(symbol)
        if hit and (now - hit[0]) < self._cache_hours * 3600:
            return hit[1]

        user = f"Symbol: {symbol}\nRecent price context: {price_context or 'n/a'}\n"
        try:
            out = self._client.structured(
                system=_SYSTEM,
                user=user,
                tool_name="fundamental_tilt",
                tool_schema=_SCHEMA,
                max_tokens=300,
                use_case="general",
            )
            result = FundamentalScore(
                score=max(-1.0, min(1.0, float(out.get("score", 0.0)))),
                label=str(out.get("label", "")),
                rationale=str(out.get("rationale", "")),
                available=True,
            )
        except Exception as exc:  # cost cap, rate limit, or API error -> neutral
            result = FundamentalScore(0.0, "unavailable", f"fundamental skipped: {exc}", available=False)

        self._cache[symbol] = (now, result)
        return result
