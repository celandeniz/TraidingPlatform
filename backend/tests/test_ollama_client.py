"""OllamaClient + factory tests — no network (mock the HTTP layer)."""
import sys
import types

from backend.research.ollama_client import (
    DEFAULT_USE_CASE_MODELS, OllamaClient, _parse_json_object,
)


def _client(**kw):
    return OllamaClient(**kw)


# ---- use-case routing -----------------------------------------------------
def test_resolve_model_by_use_case():
    c = _client()
    assert c.resolve_model(use_case="coding", deep=False) == "qwen2.5-coder:14b"
    assert c.resolve_model(use_case="reasoning", deep=False) == "deepseek-r1:14b"
    assert c.resolve_model(use_case="lightweight", deep=False) == "gemma3:12b"


def test_resolve_model_default_and_deep():
    c = _client(default_use_case="general", deep_use_case="reasoning")
    assert c.resolve_model(use_case=None, deep=False) == DEFAULT_USE_CASE_MODELS["general"]
    assert c.resolve_model(use_case=None, deep=True) == DEFAULT_USE_CASE_MODELS["reasoning"]


def test_custom_model_map_overrides():
    c = _client(use_case_models={"general": "my-model:latest"})
    assert c.resolve_model(use_case="general", deep=False) == "my-model:latest"
    # unspecified use-cases keep defaults
    assert c.resolve_model(use_case="fast", deep=False) == DEFAULT_USE_CASE_MODELS["fast"]


def test_spent_usd_is_zero_local():
    assert _client().spent_usd == 0.0


# ---- role-based selection -------------------------------------------------
def test_role_resolves_to_model():
    c = _client()
    assert c.model_for_role("analysis") == "deepseek-r1:14b"      # reasoning
    assert c.model_for_role("azure_devops") == "qwen2.5-coder:14b"  # coding
    assert c.model_for_role("d365_consultant") == "qwen3:14b"     # general


def test_manual_model_override_wins_over_role():
    c = _client()
    # explicit model beats role
    assert c.resolve_model(role="analysis", model="gemma3:12b") == "gemma3:12b"


def test_role_overrides_use_case():
    c = _client()
    # role present -> its use_case wins over a passed use_case
    assert c.resolve_model(role="analysis", use_case="fast") == "deepseek-r1:14b"


def test_available_roles_maps_all():
    roles = _client().available_roles()
    assert roles["analysis"] == "deepseek-r1:14b"
    assert roles["azure_devops"] == "qwen2.5-coder:14b"
    assert len(roles) == 6


def test_custom_role_map_overrides():
    c = _client(role_use_cases={"analysis": "lightweight"})
    assert c.model_for_role("analysis") == "gemma3:12b"  # remapped to lightweight


# ---- JSON parsing tolerance ----------------------------------------------
def test_parse_plain_json():
    assert _parse_json_object('{"side": "long", "confidence": 0.7}', "vote")["side"] == "long"


def test_parse_strips_think_block():
    raw = "<think>let me reason...</think>\n{\"side\": \"short\", \"confidence\": 0.5}"
    out = _parse_json_object(raw, "vote")
    assert out["side"] == "short"


def test_parse_strips_code_fence():
    raw = "```json\n{\"approve\": true, \"adjusted_confidence\": 0.4, \"note\": \"ok\"}\n```"
    out = _parse_json_object(raw, "risk")
    assert out["approve"] is True


def test_parse_grabs_outer_braces_with_preamble():
    raw = "Here is my answer: {\"side\": \"pass\", \"confidence\": 0.0, \"rationale\": \"x\"} done"
    assert _parse_json_object(raw, "vote")["side"] == "pass"


# ---- structured() drives the HTTP call with the right model ---------------
def test_structured_posts_resolved_model(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": '{"side":"long","confidence":0.9,"rationale":"r"}'}}

    fake_requests = types.SimpleNamespace(
        post=lambda url, json, timeout: (captured.update(payload=json, url=url) or FakeResp())
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    c = _client()
    out = c.structured(system="s", user="u", tool_name="vote",
                       tool_schema={"type": "object"}, use_case="reasoning")
    assert out["side"] == "long"
    assert captured["payload"]["model"] == "deepseek-r1:14b"   # reasoning -> deepseek
    assert captured["payload"]["format"] == {"type": "object"}  # schema passed natively
    assert captured["url"].endswith("/api/chat")


# ---- factory provider selection -------------------------------------------
def test_factory_builds_ollama_when_reachable(monkeypatch):
    from backend.research import llm_factory

    class FakeResp:
        def raise_for_status(self): pass

    fake_requests = types.SimpleNamespace(get=lambda url, timeout: FakeResp())
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    class S:
        anthropic_api_key = ""

    cfg = {"research": {"llm": {"provider": "ollama", "ollama": {}}}}
    client = llm_factory.build_llm_client(S(), cfg)
    assert type(client).__name__ == "OllamaClient"


def test_factory_returns_none_when_nothing_available(monkeypatch):
    from backend.research import llm_factory

    def _raise(*a, **k):
        raise OSError("connection refused")

    fake_requests = types.SimpleNamespace(get=_raise)
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    class S:
        anthropic_api_key = ""  # no claude fallback either

    cfg = {"research": {"llm": {"provider": "ollama", "ollama": {}}}}
    assert llm_factory.build_llm_client(S(), cfg) is None
