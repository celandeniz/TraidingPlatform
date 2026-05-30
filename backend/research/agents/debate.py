"""Bull vs Bear multi-round debate.

Two roles share one schema; only the lens differs. Bull argues FOR the proposed
trade side, Bear AGAINST. Cost control: the static analyst digest lives in the
(cached) system block — identical every turn; each user message carries only the
last opposing argument, so per-call input is O(1), not O(rounds).
"""
from __future__ import annotations

from typing import Optional

from ..base import DebateTurn
from ..llm import ClaudeClient
from .schemas import DEBATE_SCHEMA

ROUND_HARD_CAP = 3

_SYSTEM = {
    "bull": (
        "You are the BULL researcher. Argue FOR taking the proposed trade. Use the "
        "analyst digest in your context. Rebut the bear's last point if given. Be "
        "concrete and concise. Not investment advice."
    ),
    "bear": (
        "You are the BEAR researcher. Argue AGAINST the proposed trade — surface "
        "risks, crowding, catalyst danger, mean-reversion exhaustion. Rebut the "
        "bull's last point if given. Be concrete and concise. Not investment advice."
    ),
}


def _last_opponent(transcript: list[DebateTurn], role: str) -> Optional[str]:
    opp = "bear" if role == "bull" else "bull"
    for turn in reversed(transcript):
        if turn.side == opp:
            return turn.argument
    return None


def run_debate(
    client: ClaudeClient, symbol: str, *, side: str, analyst_digest: str,
    max_rounds: int = 1, deep: bool = False,
) -> list[DebateTurn]:
    rounds = max(1, min(max_rounds, ROUND_HARD_CAP))
    transcript: list[DebateTurn] = []
    for r in range(1, rounds + 1):
        for role in ("bull", "bear"):
            opp = _last_opponent(transcript, role)
            system = f"{_SYSTEM[role]}\n\nAnalyst digest:\n{analyst_digest}"
            user = (
                f"Symbol: {symbol}\nProposed trade side: {side}\nRound {r}.\n"
                + (f"Opponent's last argument: {opp}\n" if opp else "")
                + "State your argument."
            )
            out = client.structured(
                system=system, user=user, tool_name="argue",
                tool_schema=DEBATE_SCHEMA, max_tokens=300, deep=deep,
            )
            transcript.append(DebateTurn(
                side=role, round=r,
                argument=str(out.get("argument", "")),
                strongest_point=str(out.get("strongest_point", "")),
            ))
    return transcript
