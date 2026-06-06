"""Google Gemini client — same structured() interface as Claude/Ollama.

A third, drop-in LLM provider behind llm_factory. Uses the `google-genai` SDK
(imported lazily) and Gemini's JSON response mode so the tool-schema contract is
identical to the other providers — every research agent calls structured() the
same way regardless of backend.

Use-case routing (general/fast/reasoning/lightweight) maps to Gemini model tiers;
a config map can override the names. Rate limiting + a best-effort daily cost cap
mirror ClaudeClient so the agents degrade gracefully the same way.

Clean-room: written against the public google-genai API.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .ollama_client import _parse_json_object  # shared tolerant JSON parser

DEFAULT_USE_CASE_MODELS = {
    "general": "gemini-2.0-flash",
    "fast": "gemini-2.0-flash",
    "coding": "gemini-2.0-flash",
    "reasoning": "gemini-2.5-pro",
    "lightweight": "gemini-2.0-flash-lite",
}

DEFAULT_ROLE_USE_CASES = {
    "general_ai": "general", "d365_consultant": "general", "azure_devops": "coding",
    "pmo": "general", "proposal": "general", "analysis": "reasoning",
}

# Rough per-1K-token USD (flash tier); only used for the soft daily cap estimate.
_EST_USD_PER_1K = 0.0005


class GeminiUnavailable(RuntimeError):
    pass


class CostCapExceeded(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


@dataclass
class _Usage:
    spent_usd: float = 0.0
    call_times: list = field(default_factory=list)


class GeminiClient:
    def __init__(self, api_key: str, *, use_case_models: dict | None = None,
                 role_use_cases: dict | None = None, default_use_case: str = "general",
                 deep_use_case: str = "reasoning", max_calls_per_min: int = 30,
                 daily_cost_cap_usd: float = 5.0):
        self._api_key = api_key
        self.models = {**DEFAULT_USE_CASE_MODELS, **(use_case_models or {})}
        self.roles = {**DEFAULT_ROLE_USE_CASES, **(role_use_cases or {})}
        self.default_use_case = default_use_case
        self.deep_use_case = deep_use_case
        self.max_calls_per_min = max_calls_per_min
        self.daily_cost_cap_usd = daily_cost_cap_usd
        self._usage = _Usage()
        self._lock = threading.Lock()
        self._client = None  # lazily created google-genai Client

    def _genai(self):
        if self._client is None:
            from google import genai  # lazy: only when Gemini is actually used

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @property
    def spent_usd(self) -> float:
        return self._usage.spent_usd

    def resolve_model(self, *, use_case: str | None = None, role: str | None = None,
                      model: str | None = None, deep: bool = False) -> str:
        if model:
            return model
        uc = self.roles.get(role) if role else None
        uc = uc or use_case or (self.deep_use_case if deep else self.default_use_case)
        return self.models.get(uc, self.models.get("general", "gemini-2.0-flash"))

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
        """Force a JSON object matching tool_schema; return it as a dict."""
        self._precheck(clock())
        model = self.resolve_model(use_case=use_case, role=role, model=model, deep=deep)
        client = self._genai()

        # Prefer native JSON-schema response; fall back to JSON mime + prompt if the
        # SDK/model rejects the raw schema dict. The config is a GenerateContentConfig
        # when the SDK is present, else a plain dict (used by injected fakes/tests).
        def _config(with_schema: bool):
            kw = dict(system_instruction=system, temperature=0.2,
                      max_output_tokens=max(max_tokens, 512),
                      response_mime_type="application/json")
            if with_schema:
                kw["response_schema"] = tool_schema
            try:
                from google.genai import types

                return types.GenerateContentConfig(**kw)
            except Exception:  # noqa: BLE001 - SDK absent (tests) -> plain dict
                return kw

        try:
            try:
                resp = client.models.generate_content(model=model, contents=user,
                                                       config=_config(True))
            except Exception:  # noqa: BLE001 - schema dict not accepted -> mime-only
                resp = client.models.generate_content(
                    model=model,
                    contents=f"{user}\n\nReturn ONLY JSON matching this schema: {tool_schema}",
                    config=_config(False))
        except Exception as exc:  # noqa: BLE001
            raise GeminiUnavailable(f"gemini call failed ({model}): {exc}") from exc

        # Best-effort cost accounting from usage metadata.
        try:
            um = getattr(resp, "usage_metadata", None)
            total = getattr(um, "total_token_count", 0) or 0
            with self._lock:
                self._usage.spent_usd += (total / 1000.0) * _EST_USD_PER_1K
        except Exception:  # noqa: BLE001
            pass

        return _parse_json_object(resp.text or "", tool_name)
