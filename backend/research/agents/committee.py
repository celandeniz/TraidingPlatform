"""Committee orchestration: analysts -> bull/bear debate -> trader -> risk.

Hand-rolled on the existing ClaudeClient choke point (shared daily cost cap,
rate limit, prompt caching) — no LangGraph. Degrades to available=False on
cost-cap / rate-limit / any error, so the decision layer ignores it and the
system keeps running (same contract as fundamental/copilot/personas).
"""
from __future__ import annotations

from ..base import CatalystVerdict, CommitteeVerdict
from ..llm import ClaudeClient, CostCapExceeded, RateLimited
from ..personas.portfolio_manager import consensus
from .analysts import run_analysts, summarize_reports
from .debate import run_debate
from .risk_manager import run_risk
from .trader import run_trader


def run_committee(
    client: ClaudeClient, symbol: str, side: str, *,
    context: str, headlines: list[str], gate: CatalystVerdict,
    bb_meta: dict, cfg: dict,
) -> CommitteeVerdict:
    start_spent = client.spent_usd
    analysts = []
    try:
        analysts = run_analysts(
            client, symbol, context=context, headlines=headlines,
            gate=gate, bb_meta=bb_meta, deep=cfg.get("deep_analysts", False),
        )
        digest = summarize_reports(analysts)
        debate = run_debate(
            client, symbol, side=side, analyst_digest=digest,
            max_rounds=cfg.get("debate_rounds", 1), deep=cfg.get("deep_debate", False),
        )
        trader = run_trader(
            client, symbol, side=side, analyst_digest=digest, debate=debate,
            deep=cfg.get("deep_trader", True),
        )
        v_side, conf, note = run_risk(client, trader, cfg.get("risk_llm", False))
        return CommitteeVerdict(
            symbol=symbol, side=v_side, confidence=conf,
            rationale=f"{trader.rationale} | {note}",
            analyst_reports=analysts, debate=debate, trader=trader,
            rounds_run=len(debate) // 2, cost_usd=client.spent_usd - start_spent,
            available=True,
        )
    except (CostCapExceeded, RateLimited) as exc:
        return _degraded(symbol, analysts, str(exc), cfg, client.spent_usd - start_spent)
    except Exception as exc:  # noqa: BLE001
        return _degraded(symbol, analysts, str(exc), cfg, client.spent_usd - start_spent)


def _degraded(symbol, analysts, err, cfg, cost) -> CommitteeVerdict:
    # Optional cheap fallback: weighted persona consensus from any analyst votes.
    side, conf, rationale = "pass", 0.0, f"committee unavailable: {err}"
    if cfg.get("fallback_to_consensus", True) and analysts:
        from ..base import PersonaVote

        votes = [PersonaVote(a.role, a.side, a.confidence, a.rationale) for a in analysts]
        c = consensus(votes, cfg.get("weights", {}))
        side, conf = c["side"], abs(c["score"])
        rationale = f"committee degraded ({err}); consensus fallback"
    return CommitteeVerdict(
        symbol=symbol, side=side, confidence=conf, rationale=rationale,
        analyst_reports=analysts, available=False, error=err, cost_usd=cost,
    )
