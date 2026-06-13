"""The ONLY bridge from a Vibe order proposal to our order pipeline.

Hard rule: this module routes a proposal through `Toolset.submit_order` and
NOTHING else. It contains no broker code and MUST NOT import any executor or
`backend.execution.live` — so a Vibe proposal physically cannot reach a live
broker. It inherits every guarantee of the OMS path: audit ledger, guard
pipeline, risk manager, and the live-trading hard-block (a live executor only
exists when settings.live_trading is set, independent of this module).

A guard test (backend/tests/test_vibe_execution_routing.py) asserts the no-live
import rule statically.
"""
from __future__ import annotations

from .schemas import VibeOrderProposal


def route_proposal(proposal: dict, toolset) -> dict:
    """Validate a Vibe order proposal and submit it through the OMS-backed Toolset.

    Returns the Toolset's defensive result dict (with source="vibe" added), or a
    rejection dict if the proposal doesn't parse. Never raises.
    """
    try:
        parsed = VibeOrderProposal.from_vibe_dict(proposal)
    except ValueError as exc:
        return {"ok": False, "source": "vibe", "stage": "validation",
                "detail": f"rejected proposal: {exc}"}

    result = toolset.submit_order(
        parsed.symbol, parsed.side, parsed.qty,
        reduce_only=parsed.reduce_only,
        message=f"via Vibe: {parsed.rationale}".strip().rstrip(":"),
    )
    if isinstance(result, dict):
        result.setdefault("source", "vibe")
        return result
    return {"ok": False, "source": "vibe", "detail": "unexpected toolset result"}
