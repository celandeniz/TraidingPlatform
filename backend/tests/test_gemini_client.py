"""Gemini client tests — no network (fake google-genai client injected)."""
import types

import pytest

from backend.research.gemini_client import (
    CostCapExceeded,
    GeminiClient,
    RateLimited,
)


class _Resp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = types.SimpleNamespace(total_token_count=120)


class _FakeModels:
    def __init__(self, text):
        self._text = text
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents})
        return _Resp(self._text)


class _FakeGenaiClient:
    def __init__(self, text):
        self.models = _FakeModels(text)


def _client(text='{"answer": "hi"}'):
    c = GeminiClient("fake-key")
    c._client = _FakeGenaiClient(text)  # inject; bypasses lazy google-genai import
    return c


def test_resolve_model_routing():
    c = GeminiClient("k")
    assert c.resolve_model() == "gemini-2.0-flash"
    assert c.resolve_model(deep=True) == "gemini-2.5-pro"          # reasoning tier
    assert c.resolve_model(role="analysis") == "gemini-2.5-pro"    # role -> reasoning
    assert c.resolve_model(model="gemini-x") == "gemini-x"         # manual override wins


def test_structured_parses_json():
    c = _client('{"answer": "hello"}')
    out = c.structured(system="s", user="u", tool_name="answer",
                       tool_schema={"type": "object"}, clock=lambda: 0.0)
    assert out == {"answer": "hello"}
    assert c.spent_usd > 0  # cost estimated from usage metadata


def test_rate_limit_raises():
    c = _client()
    c.max_calls_per_min = 2
    t = 0.0
    c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: t)
    c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: t)
    with pytest.raises(RateLimited):
        c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: t)


def test_cost_cap_raises():
    c = _client()
    c.daily_cost_cap_usd = 0.0  # already at cap
    with pytest.raises(CostCapExceeded):
        c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: 0.0)


def test_available_roles():
    c = GeminiClient("k")
    roles = c.available_roles()
    assert roles["analysis"] == "gemini-2.5-pro" and "general_ai" in roles
