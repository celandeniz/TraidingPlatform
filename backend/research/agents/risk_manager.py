"""Final risk pass — can only LOWER confidence or flip to pass, never amplify.

Either a pure-Python conservative rule (default) or one Claude call (risk_llm).
"""
from __future__ import annotations

from ..base import TraderView
from ..llm import ClaudeClient
from .schemas import RISK_SCHEMA

_SYSTEM = (
    "You are the risk manager. You may only REDUCE the trader's confidence or veto "
    "(set approve=false). Never increase confidence. Be conservative. Not advice."
)


def run_risk_python(trader: TraderView) -> tuple[str, float, str]:
    """Pure rule: shave low-confidence trades to pass."""
    if trader.side == "pass" or trader.confidence < 0.4:
        return "pass", min(trader.confidence, 0.4), "low conviction -> pass"
    return trader.side, trader.confidence, "approved (python risk rule)"


def run_risk(client: ClaudeClient, trader: TraderView, use_llm: bool) -> tuple[str, float, str]:
    if not use_llm:
        return run_risk_python(trader)
    try:
        out = client.structured(
            system=_SYSTEM,
            user=f"Trader: side={trader.side} conf={trader.confidence:.2f} "
                 f"rationale={trader.rationale} risk={trader.key_risk}\nReview.",
            tool_name="risk_review", tool_schema=RISK_SCHEMA, max_tokens=200,
            use_case="lightweight",
        )
        approve = bool(out.get("approve", True))
        adj = max(0.0, min(float(out.get("adjusted_confidence", trader.confidence)),
                           trader.confidence))  # clamp: never above trader
        if not approve:
            return "pass", adj, str(out.get("note", "vetoed"))
        return trader.side, adj, str(out.get("note", "approved"))
    except Exception as exc:  # noqa: BLE001 - degrade to python rule
        side, conf, _ = run_risk_python(trader)
        return side, conf, f"risk-llm unavailable ({exc}); python rule"
