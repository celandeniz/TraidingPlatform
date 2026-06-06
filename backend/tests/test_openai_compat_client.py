"""OpenAI-compatible client (DeepSeek/Qwen) tests — no network (fake requests)."""
import sys
import types

import pytest

from backend.research.openai_compat_client import (
    CostCapExceeded,
    OpenAICompatClient,
    RateLimited,
)


@pytest.fixture(autouse=True)
def _restore_requests():
    """Save/restore the real `requests` so the injected fake never leaks to other tests."""
    saved = sys.modules.get("requests")
    yield
    if saved is not None:
        sys.modules["requests"] = saved
    else:
        sys.modules.pop("requests", None)


def _install_fake_requests(content='{"answer": "hi"}', total_tokens=120, status=200):
    """Register a stub `requests` whose POST returns one chat-completion body."""
    mod = types.ModuleType("requests")

    class _Resp:
        def __init__(self):
            self.calls = []

        def json(self):
            return {"choices": [{"message": {"content": content}}],
                    "usage": {"total_tokens": total_tokens}}

        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")

    holder = {"last": None}

    def post(url, json=None, headers=None, timeout=None):
        holder["last"] = {"url": url, "json": json, "headers": headers}
        return _Resp()

    mod.post = post
    mod._holder = holder
    sys.modules["requests"] = mod
    return mod


def test_resolve_model_routing():
    c = OpenAICompatClient("k")
    assert c.resolve_model() == "deepseek-chat"
    assert c.resolve_model(deep=True) == "deepseek-reasoner"
    assert c.resolve_model(role="analysis") == "deepseek-reasoner"
    assert c.resolve_model(model="x") == "x"


def test_structured_parses_and_hits_endpoint():
    m = _install_fake_requests('{"answer": "hello"}')
    c = OpenAICompatClient("key", base_url="https://api.deepseek.com")
    out = c.structured(system="s", user="u", tool_name="answer",
                       tool_schema={"type": "object"}, clock=lambda: 0.0)
    assert out == {"answer": "hello"}
    assert m._holder["last"]["url"] == "https://api.deepseek.com/chat/completions"
    assert m._holder["last"]["headers"]["Authorization"] == "Bearer key"
    assert c.spent_usd > 0


def test_rate_limit_and_cost_cap():
    _install_fake_requests()
    c = OpenAICompatClient("k"); c.max_calls_per_min = 1
    c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: 0.0)
    with pytest.raises(RateLimited):
        c.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: 0.0)
    c2 = OpenAICompatClient("k"); c2.daily_cost_cap_usd = 0.0
    with pytest.raises(CostCapExceeded):
        c2.structured(system="s", user="u", tool_name="a", tool_schema={}, clock=lambda: 0.0)


def test_available_roles():
    assert OpenAICompatClient("k").available_roles()["analysis"] == "deepseek-reasoner"


def test_factory_deepseek_fallback_without_key():
    from backend.research.llm_factory import build_llm_client

    class S:  # no deepseek key -> falls back through the chain (returns something or None)
        pass
    # should not raise; provider=deepseek with no key degrades gracefully
    build_llm_client(S(), {"research": {"llm": {"provider": "deepseek"}}})
