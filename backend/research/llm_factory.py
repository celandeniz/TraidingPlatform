"""LLM provider factory — choose Ollama (local, default) or Claude per config.

Both clients expose the same structured() interface, so agents are
provider-agnostic. Use-case routing (general/fast/coding/reasoning/lightweight)
is handled inside OllamaClient; the Claude client maps use_case -> model/deep.

Returns None when no provider is usable (no Ollama reachable, no Anthropic key),
so the research layer degrades gracefully exactly like before.
"""
from __future__ import annotations

from typing import Optional


def build_llm_client(settings, cfg: dict):
    """Build the configured LLM client, or None if unavailable.

    config research.llm.provider: "ollama" (default) | "claude".
    Falls back ollama->claude (and vice-versa) if the primary isn't usable.
    """
    llm = cfg.get("research", {}).get("llm", {})
    provider = llm.get("provider", "ollama")

    if provider == "ollama":
        client = _try_ollama(llm)
        if client is not None:
            return client
        return _try_claude(settings, llm)  # fallback

    # provider == "claude"
    client = _try_claude(settings, llm)
    if client is not None:
        return client
    return _try_ollama(llm)  # fallback


def _try_ollama(llm: dict):
    from .ollama_client import OllamaClient

    ocfg = llm.get("ollama", {})
    host = ocfg.get("host", "http://localhost:11434")
    try:
        import requests

        requests.get(f"{host.rstrip('/')}/api/tags", timeout=2).raise_for_status()
    except Exception:  # noqa: BLE001 - ollama not running
        return None
    return OllamaClient(
        host=host,
        use_case_models=ocfg.get("models"),
        default_use_case=ocfg.get("default_use_case", "general"),
        deep_use_case=ocfg.get("deep_use_case", "reasoning"),
        max_calls_per_min=llm.get("max_calls_per_min", 60),
        request_timeout=ocfg.get("request_timeout", 120.0),
    )


def _try_claude(settings, llm: dict):
    key = getattr(settings, "anthropic_api_key", "")
    if not key:
        return None
    from .llm import ClaudeClient

    return ClaudeClient(
        key,
        model=llm.get("model", "claude-haiku-4-5-20251001"),
        model_deep=llm.get("model_deep", "claude-opus-4-8"),
        max_calls_per_min=llm.get("max_calls_per_min", 20),
        daily_cost_cap_usd=llm.get("daily_cost_cap_usd", 5.0),
    )


# Use-case hints for each committee stage (passed to structured(use_case=...)).
# Ollama routes these to the best local model; Claude ignores them (uses deep flag).
STAGE_USE_CASE = {
    "analyst": "fast",        # 5 cheap votes -> faster general
    "debate": "general",      # argumentation -> best general
    "trader": "reasoning",    # synthesis decision -> reasoning model
    "risk": "lightweight",    # quick conservative check -> lightweight
    "copilot": "general",
    "fundamental": "general",
}
