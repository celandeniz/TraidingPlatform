"""OpenAI-compatible LLM client — DeepSeek / Qwen(DashScope) / SiliconFlow.

A fourth provider behind llm_factory, exposing the same structured() interface as
Claude/Ollama/Gemini. Talks to any OpenAI-compatible /chat/completions endpoint
via `requests` (no new dependency) using JSON response mode, so the tool-schema
contract is identical to the other providers.

Defaults to DeepSeek; point `base_url` at DashScope/SiliconFlow/etc. to switch.
Use-case routing maps to model tiers (general/fast/reasoning); rate limit + a
soft daily cost cap mirror the other cloud clients.

Clean-room: standard OpenAI chat-completions API; no TradingAgents-CN code.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .ollama_client import _parse_json_object  # shared tolerant JSON parser

# DeepSeek default tiers; override via config research.llm.openai.models.
DEFAULT_USE_CASE_MODELS = {
    "general": "deepseek-chat",
    "fast": "deepseek-chat",
    "coding": "deepseek-chat",
    "reasoning": "deepseek-reasoner",
    "lightweight": "deepseek-chat",
}

DEFAULT_ROLE_USE_CASES = {
    "general_ai": "general", "d365_consultant": "general", "azure_devops": "coding",
    "pmo": "general", "proposal": "general", "analysis": "reasoning",
}

_EST_USD_PER_1K = 0.0003  # rough DeepSeek-tier estimate, soft cap only


class OpenAICompatUnavailable(RuntimeError):
    pass


class CostCapExceeded(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


@dataclass
class _Usage:
    spent_usd: float = 0.0
    call_times: list = field(default_factory=list)


class OpenAICompatClient:
    def __init__(self, api_key: str, *, base_url: str = "https://api.deepseek.com",
                 use_case_models: dict | None = None, role_use_cases: dict | None = None,
                 default_use_case: str = "general", deep_use_case: str = "reasoning",
                 max_calls_per_min: int = 30, daily_cost_cap_usd: float = 5.0,
                 request_timeout: float = 60.0):
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.models = {**DEFAULT_USE_CASE_MODELS, **(use_case_models or {})}
        self.roles = {**DEFAULT_ROLE_USE_CASES, **(role_use_cases or {})}
        self.default_use_case = default_use_case
        self.deep_use_case = deep_use_case
        self.max_calls_per_min = max_calls_per_min
        self.daily_cost_cap_usd = daily_cost_cap_usd
        self.request_timeout = request_timeout
        self._usage = _Usage()
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        return self._usage.spent_usd

    def resolve_model(self, *, use_case: str | None = None, role: str | None = None,
                      model: str | None = None, deep: bool = False) -> str:
        if model:
            return model
        uc = self.roles.get(role) if role else None
        uc = uc or use_case or (self.deep_use_case if deep else self.default_use_case)
        return self.models.get(uc, self.models.get("general", "deepseek-chat"))

    def model_for_role(self, role: str) -> str:
        return self.resolve_model(role=role)

    def available_roles(self) -> dict:
        return {r: self.model_for_role(r) for r in self.roles}

    def _precheck(self, now: float) -> None:
        with self._lock:
            window = [t for t in self._usage.call_times if now - t < 60.0]
            self._usage.call_times = window
            if len(window) >= self.max_calls_per_min:
                raise RateLimited(f"> {self.max_calls_per_min} calls/min")
            if self._usage.spent_usd >= self.daily_cost_cap_usd:
                raise CostCapExceeded(f"daily cap ${self.daily_cost_cap_usd} reached")
            self._usage.call_times.append(now)

    def structured(self, *, system: str, user: str, tool_name: str, tool_schema: dict,
                   max_tokens: int = 700, deep: bool = False, cache_system: bool = True,
                   clock=time.monotonic, use_case: str | None = None,
                   role: str | None = None, model: str | None = None) -> dict:
        """Force a JSON object via OpenAI-compatible chat completions; return a dict."""
        import requests

        self._precheck(clock())
        model = self.resolve_model(use_case=use_case, role=role, model=model, deep=deep)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                # nudge JSON since some compat servers require the word "json" present
                {"role": "user", "content": f"{user}\n\nReturn ONLY a JSON object."},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max(max_tokens, 512),
            "temperature": 0.2,
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions", json=payload,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                timeout=self.request_timeout)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise OpenAICompatUnavailable(f"call failed ({model}): {exc}") from exc

        body = resp.json()
        try:
            total = (body.get("usage", {}) or {}).get("total_tokens", 0) or 0
            with self._lock:
                self._usage.spent_usd += (total / 1000.0) * _EST_USD_PER_1K
        except Exception:  # noqa: BLE001
            pass

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAICompatUnavailable(f"malformed response for {tool_name}") from exc
        return _parse_json_object(content, tool_name)
