"""Tests for the LLM-backed agents using a MOCK client (no live Claude calls)."""
from backend.research.fundamental_agent import FundamentalAgent
from backend.research.personas.portfolio_manager import consensus
from backend.research.base import PersonaVote


class FakeClient:
    """Stand-in for ClaudeClient.structured returning canned tool outputs."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def structured(self, **kwargs):
        self.calls += 1
        return self.payload


def test_fundamental_agent_parses_and_clamps():
    c = FakeClient({"score": 1.7, "label": "quality", "rationale": "strong margins"})
    agent = FundamentalAgent(c, cache_hours=24)
    t = [0.0]
    s = agent.score("AAPL", clock=lambda: t[0])
    assert s.available is True
    assert s.score == 1.0  # clamped from 1.7
    assert s.label == "quality"


def test_fundamental_agent_caches():
    c = FakeClient({"score": 0.2, "label": "ok", "rationale": "x"})
    agent = FundamentalAgent(c, cache_hours=24)
    t = [0.0]
    agent.score("AAPL", clock=lambda: t[0])
    agent.score("AAPL", clock=lambda: t[0])  # within cache window
    assert c.calls == 1  # second call served from cache


def test_consensus_long_when_value_and_momentum_agree():
    votes = [
        PersonaVote("value", "long", 0.8, ""),
        PersonaVote("momentum", "long", 0.7, ""),
        PersonaVote("sentiment", "pass", 0.0, ""),
        PersonaVote("contrarian", "short", 0.3, ""),
    ]
    weights = {"value": 1.0, "momentum": 1.0, "sentiment": 1.0, "contrarian": 1.2}
    out = consensus(votes, weights)
    assert out["side"] == "long"


def test_consensus_pass_when_balanced():
    votes = [
        PersonaVote("value", "long", 0.5, ""),
        PersonaVote("contrarian", "short", 0.5, ""),
    ]
    out = consensus(votes, {"value": 1.0, "contrarian": 1.0})
    assert out["side"] == "pass"
