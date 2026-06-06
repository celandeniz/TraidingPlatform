"""Combine signal + confirmation + catalyst gate (+ optional fundamental/persona)
into a final Decision.

Pure function: hand it the pieces, get a Decision. The gate is authoritative for
suppression (Ek-1 §E1.5).
"""
from __future__ import annotations

from typing import Optional

from .base import CatalystVerdict, CommitteeVerdict, Decision, FundamentalScore, Side


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
    allow_spot_short: bool = False,
    committee: Optional[CommitteeVerdict] = None,
    committee_mode: str = "off",  # off | confirm | veto | decide
    committee_veto_confidence: float = 0.6,
    reflections: Optional[list] = None,  # past-trade lessons (audit/context only)
) -> Decision:
    """Map (signal side, tier, regime) + gate -> action, applying the gate rule.

    Action matrix:
      high_vol + buy  -> CALL ;  high_vol + sell -> PUT
      core    + buy   -> SPOT_LONG
      core    + sell  -> SPOT_SHORT if allow_spot_short else NONE

    allow_spot_short gates equity shorting (needs a margin account); crypto
    callers pass it True since crypto shorts are native.
    """
    confirmations: dict = {}
    if reflections:
        confirmations["reflections"] = reflections  # surfaced for audit + LLM context
    if bollinger is not None:
        confirmations["bollinger"] = bollinger
    if fundamental is not None:
        confirmations["fundamental"] = {
            "score": fundamental.score,
            "label": fundamental.label,
            "available": fundamental.available,
        }
    if committee is not None and committee_mode != "off":
        confirmations["committee"] = {
            "side": committee.side,
            "confidence": committee.confidence,
            "available": committee.available,
            "rationale": committee.rationale,
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

    # Committee influence (gate already passed; gate stays authoritative above).
    # Only acts when a verdict is present, available, and mode is veto/decide.
    if committee is not None and committee.available and committee_mode in ("veto", "decide"):
        committee_side = {"long": "buy", "short": "sell"}.get(committee.side)
        if committee_mode == "veto":
            opposes = committee.side == "pass" or (
                committee_side is not None and committee_side != side
            )
            if opposes and committee.confidence >= committee_veto_confidence:
                return Decision(symbol, "NONE", gate.verdict, None,
                                rationale=f"committee veto ({committee.side} "
                                          f"{committee.confidence:.2f})",
                                confirmations=confirmations)
        elif committee_mode == "decide":
            if committee.side == "pass":
                return Decision(symbol, "NONE", gate.verdict, None,
                                rationale="committee: pass", confirmations=confirmations)
            side = committee_side  # committee drives the action mapping

    # Map to action by tier.
    if tier == "high_vol":
        action = "CALL" if side == "buy" else "PUT"
    else:  # core
        if side == "buy":
            action = "SPOT_LONG"
        else:
            action = "SPOT_SHORT" if allow_spot_short else "NONE"

    rationale = f"{gate.verdict}; regime={regime}; tier={tier}"
    return Decision(symbol, action, gate.verdict, side, rationale, confirmations)
