"""Combine signal + confirmation + catalyst gate (+ optional fundamental/persona)
into a final Decision.

Pure function: hand it the pieces, get a Decision. The gate is authoritative for
suppression (Ek-1 §E1.5).
"""
from __future__ import annotations

from typing import Optional

from .base import CatalystVerdict, Decision, FundamentalScore, Side


def decide(
    symbol: str,
    side: Side,
    *,
    tier: str,
    regime: str,
    gate: CatalystVerdict,
    bollinger: Optional[dict] = None,
    fundamental: Optional[FundamentalScore] = None,
    fundamental_can_veto: bool = False,
) -> Decision:
    """Map (signal side, tier, regime) + gate -> action, applying the gate rule.

    Action matrix (Phase 1/2 subset):
      high_vol + buy  -> CALL ;  high_vol + sell -> PUT
      core    + buy   -> SPOT_LONG ; core + sell -> NONE (no spot short in v1)
    """
    confirmations: dict = {}
    if bollinger is not None:
        confirmations["bollinger"] = bollinger
    if fundamental is not None:
        confirmations["fundamental"] = {
            "score": fundamental.score,
            "label": fundamental.label,
            "available": fundamental.available,
        }

    # Gate: suppression is authoritative.
    if gate.verdict == "SUPPRESS":
        return Decision(symbol, "NONE", gate.verdict, None,
                        rationale="catalyst: " + "; ".join(gate.reasons),
                        confirmations=confirmations)

    # WITH_TREND_ONLY: drop counter-trend fades.
    if gate.verdict == "WITH_TREND_ONLY":
        counter_trend = (side == "buy" and regime == "down") or (
            side == "sell" and regime == "up"
        )
        if counter_trend:
            return Decision(symbol, "NONE", gate.verdict, None,
                            rationale="counter-trend fade blocked by gate: "
                                      + "; ".join(gate.reasons),
                            confirmations=confirmations)

    # Optional fundamental veto (off by default).
    if fundamental_can_veto and fundamental and fundamental.available:
        if side == "buy" and fundamental.score <= -0.5:
            return Decision(symbol, "NONE", gate.verdict, None,
                            rationale=f"fundamental veto (score {fundamental.score:+.2f})",
                            confirmations=confirmations)
        if side == "sell" and fundamental.score >= 0.5:
            return Decision(symbol, "NONE", gate.verdict, None,
                            rationale=f"fundamental veto (score {fundamental.score:+.2f})",
                            confirmations=confirmations)

    # Map to action by tier.
    if tier == "high_vol":
        action = "CALL" if side == "buy" else "PUT"
    else:  # core
        action = "SPOT_LONG" if side == "buy" else "NONE"

    rationale = f"{gate.verdict}; regime={regime}; tier={tier}"
    return Decision(symbol, action, gate.verdict, side, rationale, confirmations)
