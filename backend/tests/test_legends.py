"""Legend personas: 5 distinct lenses on the shared Persona base."""
from __future__ import annotations

from backend.research.personas.legends import LEGEND_NAMES, build_legend_personas


class FakeClient:
    """Records the system prompt of each structured call; returns a fixed vote."""

    def __init__(self):
        self.systems = []

    def structured(self, *, system, user, tool_name, tool_schema, max_tokens,
                   deep=False, use_case="fast"):
        self.systems.append(system)
        return {"side": "pass", "confidence": 0.2, "rationale": "fake"}


def test_factory_builds_five_distinct_personas():
    client = FakeClient()
    personas = build_legend_personas(client)
    names = [p.name for p in personas]
    assert names == LEGEND_NAMES
    assert len(set(names)) == 5


def test_every_prompt_handles_missing_fundamentals_and_disclaims():
    client = FakeClient()
    for p in build_legend_personas(client):
        p.analyze("AAPL", "fundamentals: unavailable")
    assert len(client.systems) == 5
    for system in client.systems:
        assert "unavailable" in system          # pass-on-missing-data rule
        assert "Not investment advice" in system


def test_votes_flow_through_persona_base():
    client = FakeClient()
    vote = build_legend_personas(client)[0].analyze("AAPL", "ctx")
    assert vote.side == "pass" and vote.confidence == 0.2
