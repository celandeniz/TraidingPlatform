"""Trader synthesis — one call that reads the analysts + debate and decides."""
from __future__ import annotations

from ..base import DebateTurn, TraderView
from ..llm import ClaudeClient
from .schemas import TRADER_SCHEMA

_SYSTEM = (
    "You are the head trader. Given the analyst digest and the bull/bear debate, "
    "synthesize a single decision: long, short, or pass, with a calibrated "
    "confidence (0..1) and the key risk. Weigh the debate honestly; if the bear's "
    "case is strong, pass. Not investment advice."
)


def run_trader(
    client: ClaudeClient, symbol: str, *, side: str, analyst_digest: str,
    debate: list[DebateTurn], deep: bool = True,
) -> TraderView:
    debate_text = "\n".join(f"[{t.side} r{t.round}] {t.argument}" for t in debate)
    user = (
        f"Symbol: {symbol}\nProposed side: {side}\n"
        f"Analyst digest:\n{analyst_digest}\n\nDebate:\n{debate_text}\n\nDecide."
    )
    out = client.structured(
        system=_SYSTEM, user=user, tool_name="trade_decision",
        tool_schema=TRADER_SCHEMA, max_tokens=350, deep=deep,
    )
    return TraderView(
        side=str(out.get("side", "pass")),
        confidence=max(0.0, min(1.0, float(out.get("confidence", 0.0)))),
        rationale=str(out.get("rationale", "")),
        key_risk=str(out.get("key_risk", "")),
    )
