"""Aggregate persona votes into a consensus recommendation.

Weighted vote: each persona's confidence is signed (+long / -short / 0 pass) and
multiplied by its configured weight. The contrarian weight is >1 by default so the
risk voice can offset crowd agreement. Pure aggregation -> unit-testable.
"""
from __future__ import annotations

from ..base import PersonaVote


def consensus(votes: list[PersonaVote], weights: dict[str, float]) -> dict:
    score = 0.0
    total_w = 0.0
    for v in votes:
        w = weights.get(v.name, 1.0)
        total_w += w
        if v.side == "long":
            score += w * v.confidence
        elif v.side == "short":
            score -= w * v.confidence
    norm = score / total_w if total_w else 0.0
    if norm > 0.15:
        side = "long"
    elif norm < -0.15:
        side = "short"
    else:
        side = "pass"
    return {
        "side": side,
        "score": round(norm, 3),
        "votes": [
            {"name": v.name, "side": v.side, "confidence": v.confidence, "rationale": v.rationale}
            for v in votes
        ],
    }


def build_personas(client) -> list:
    from .contrarian import ContrarianPersona
    from .momentum import MomentumPersona
    from .sentiment import SentimentPersona
    from .value import ValuePersona

    return [ValuePersona(client), MomentumPersona(client), SentimentPersona(client),
            ContrarianPersona(client)]
