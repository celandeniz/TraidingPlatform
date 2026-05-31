"""Local Ollama client — same structured() interface as ClaudeClient.

Drop-in alternative LLM provider that runs entirely on localhost (no API key,
no cost). Uses Ollama's native JSON-schema structured output (`format` param on
/api/chat) so the tool-schema contract is identical to the Claude path.

Use-case routing: each call picks the best local model for its task
(general / fast / coding / reasoning / lightweight) via a config-driven map.
The agents pass a `use_case`; the client resolves it to a model name.

All research agents call structured() the same way regardless of provider.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

# Default use-case -> model map (overridable via config research.llm.ollama.models).
DEFAULT_USE_CASE_MODELS = {
    "general": "qwen3:14b",        # best general
    "fast": "qwen3:8b",            # faster general
    "coding": "qwen2.5-coder:14b",  # coding
    "reasoning": "deepseek-r1:14b",  # reasoning
    "lightweight": "gemma3:12b",   # lightweight
}


class OllamaUnavailable(RuntimeError):
    pass


# Kept for interface parity with ClaudeClient (local => never actually raised).
class CostCapExceeded(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


@dataclass
class _Usage:
    spent_usd: float = 0.0  # always 0 locally; kept for interface parity
    call_times: list = field(default_factory=list)


class OllamaClient:
    def __init__(
        self,
        *,
        host: str = "http://localhost:11434",
        use_case_models: dict | None = None,
        default_use_case: str = "general",
        deep_use_case: str = "reasoning",
        max_calls_per_min: int = 60,
        request_timeout: float = 120.0,
    ):
        self.host = host.rstrip("/")
        self.models = {**DEFAULT_USE_CASE_MODELS, **(use_case_models or {})}
        self.default_use_case = default_use_case
        self.deep_use_case = deep_use_case
        self.max_calls_per_min = max_calls_per_min
        self.request_timeout = request_timeout
        self._usage = _Usage()
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        return 0.0  # local inference is free

    def resolve_model(self, *, use_case: str | None, deep: bool) -> str:
        """Pick a model: explicit use_case wins; else deep -> reasoning, else general."""
        uc = use_case or (self.deep_use_case if deep else self.default_use_case)
        return self.models.get(uc, self.models.get("general", "qwen3:14b"))

    def _precheck(self, now: float) -> None:
        with self._lock:
            window = [t for t in self._usage.call_times if now - t < 60.0]
            self._usage.call_times = window
            if len(window) >= self.max_calls_per_min:
                raise RateLimited(f"> {self.max_calls_per_min} calls/min")
            self._usage.call_times.append(now)

    def structured(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
        max_tokens: int = 700,
        deep: bool = False,
        cache_system: bool = True,  # accepted for parity; Ollama caches its own KV
        clock=time.monotonic,
        use_case: str | None = None,
    ) -> dict:
        """Force a JSON object matching tool_schema; return it as a dict.

        Uses Ollama's structured-output `format` (JSON schema). Strips any
        <think>...</think> reasoning blocks (DeepSeek-R1) before parsing.
        """
        import requests

        self._precheck(clock())
        model = self.resolve_model(use_case=use_case, deep=deep)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": tool_schema,  # native structured output
            # Disable chain-of-thought for the structured path: thinking models
            # (qwen3, deepseek-r1) otherwise spend the token budget reasoning into
            # a separate `thinking` field and emit no JSON (done_reason: length).
            "think": False,
            "options": {"num_predict": max(max_tokens, 512), "temperature": 0.2},
        }
        try:
            resp = requests.post(f"{self.host}/api/chat", json=payload,
                                 timeout=self.request_timeout)
            if resp.status_code == 400:
                # Older Ollama / non-thinking models may reject `think`; retry without.
                payload.pop("think", None)
                resp = requests.post(f"{self.host}/api/chat", json=payload,
                                     timeout=self.request_timeout)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise OllamaUnavailable(f"ollama call failed ({model}): {exc}") from exc

        content = resp.json().get("message", {}).get("content", "")
        return _parse_json_object(content, tool_name)


def _parse_json_object(content: str, tool_name: str) -> dict:
    """Parse the model's JSON, tolerating reasoning preambles / code fences."""
    text = content.strip()
    # DeepSeek-R1 emits <think>...</think> before the answer.
    if "</think>" in text:
        text = text.split("</think>", 1)[1].strip()
    # Strip ```json fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: grab the outermost {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise RuntimeError(f"Ollama did not return valid JSON for {tool_name}: {content[:200]}")
