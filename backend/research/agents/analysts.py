"""Analyst stage — reuse the 4 personas + a news/technical analyst.

The news/technical analyst consumes data already computed elsewhere (catalyst
gate verdict, bollinger confluence meta, recent headlines) — no new fetches.
Each analyst is one cheap Claude call returning a vote.
"""
from __future__ import annotations

from ..base import AnalystReport, CatalystVerdict
from ..llm import ClaudeClient
from ..personas.base import Persona
from ..personas.portfolio_manager import build_personas


class NewsTechnicalAnalyst(Persona):
    name = "news_technical"
    system = (
        "You are a news + technical analyst. Given the catalyst-gate verdict, "
        "multi-timeframe Bollinger band positions, and recent headlines, judge "
        "whether the short-term setup favors long/short/pass. Fresh strong "
        "catalysts argue against fading; band extremes argue for mean reversion. "
        "Not investment advice."
    )


def _vote_to_report(vote, role: str) -> AnalystReport:
    available = "unavailable" not in vote.rationale
    return AnalystReport(role=role, side=vote.side, confidence=vote.confidence,
                         rationale=vote.rationale, available=available)


def run_analysts(
    client: ClaudeClient, symbol: str, *, context: str, headlines: list[str],
    gate: CatalystVerdict, bb_meta: dict, deep: bool = False,
) -> list[AnalystReport]:
    reports: list[AnalystReport] = []
    for persona in build_personas(client):
        vote = persona.analyze(symbol, context, deep=deep)
        reports.append(_vote_to_report(vote, persona.name))
    nt_context = (
        f"{context}\nCatalyst gate: {gate.verdict} ({'; '.join(gate.reasons)})\n"
        f"Bollinger score: {bb_meta.get('bb_score')} per_tf={bb_meta.get('bb_per_tf')}\n"
        f"Headlines: {headlines[:3]}"
    )
    nt_vote = NewsTechnicalAnalyst(client).analyze(symbol, nt_context, deep=deep)
    reports.append(_vote_to_report(nt_vote, "news_technical"))
    return reports


def summarize_reports(reports: list[AnalystReport]) -> str:
    """Compact digest used in the (cached) debate system block — built once."""
    return "\n".join(
        f"- {r.role}: {r.side} ({r.confidence:.2f}) — {r.rationale}" for r in reports
    )
