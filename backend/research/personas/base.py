"""Persona analyst base: a Claude call with a distinct lens -> one vote.

Each persona shares the same vote schema; only the system prompt (the lens) differs.
The portfolio manager aggregates votes. Inspired by open-source multi-analyst
designs; our own implementation.
"""
from __future__ import annotations

from ..base import PersonaVote
from ..llm import ClaudeClient

VOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "side": {"type": "string", "enum": ["long", "short", "pass"]},
        "confidence": {"type": "number", "description": "0..1"},
        "rationale": {"type": "string", "description": "<=2 sentences"},
    },
    "required": ["side", "confidence", "rationale"],
}


class Persona:
    name: str = "persona"
    system: str = ""

    def __init__(self, client: ClaudeClient):
        self._client = client

    def analyze(self, symbol: str, context: str, *, deep: bool = False,
                use_case: str = "fast") -> PersonaVote:
        try:
            out = self._client.structured(
                system=self.system,
                user=f"Symbol: {symbol}\n{context}\nGive your vote.",
                tool_name="vote",
                tool_schema=VOTE_SCHEMA,
                max_tokens=250,
                deep=deep,
                use_case=use_case,
            )
            return PersonaVote(
                name=self.name,
                side=str(out.get("side", "pass")),
                confidence=max(0.0, min(1.0, float(out.get("confidence", 0.0)))),
                rationale=str(out.get("rationale", "")),
            )
        except Exception as exc:
            return PersonaVote(self.name, "pass", 0.0, f"unavailable: {exc}")
