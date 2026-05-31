"""Claude (Anthropic) client wrapper.

Single choke point for every LLM call so we can enforce:
  * structured output (force a tool call -> validated dict, no fragile parsing)
  * prompt caching (cache_control on the system block -> repeated calls cheap)
  * rate limiting (calls/min) and a HARD daily cost cap (stop when exceeded)

All research agents call this; none import `anthropic` directly.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# Rough USD per 1M tokens (input, output). Updated occasionally; only used for the
# soft cost-cap accounting, not billing.
_PRICING = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
}
_DEFAULT_PRICE = (3.0, 15.0)


class CostCapExceeded(RuntimeError):
    pass


class RateLimited(RuntimeError):
    pass


@dataclass
class _Usage:
    spent_usd: float = 0.0
    call_times: list[float] = field(default_factory=list)


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "claude-haiku-4-5-20251001",
        model_deep: str = "claude-opus-4-8",
        max_calls_per_min: int = 20,
        daily_cost_cap_usd: float = 5.0,
    ):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self.model = model
        self.model_deep = model_deep
        self.max_calls_per_min = max_calls_per_min
        self.daily_cost_cap_usd = daily_cost_cap_usd
        self._usage = _Usage()
        self._lock = threading.Lock()

    # ---- guards -----------------------------------------------------------
    def _precheck(self, now: float) -> None:
        with self._lock:
            if self._usage.spent_usd >= self.daily_cost_cap_usd:
                raise CostCapExceeded(
                    f"daily cost cap ${self.daily_cost_cap_usd} reached "
                    f"(spent ${self._usage.spent_usd:.3f})"
                )
            window = [t for t in self._usage.call_times if now - t < 60.0]
            self._usage.call_times = window
            if len(window) >= self.max_calls_per_min:
                raise RateLimited(f"> {self.max_calls_per_min} calls/min")
            self._usage.call_times.append(now)

    def _account(self, model: str, usage) -> None:
        pin, pout = _PRICING.get(model, _DEFAULT_PRICE)
        cost = (
            (getattr(usage, "input_tokens", 0) or 0) * pin
            + (getattr(usage, "output_tokens", 0) or 0) * pout
        ) / 1_000_000.0
        with self._lock:
            self._usage.spent_usd += cost

    @property
    def spent_usd(self) -> float:
        return self._usage.spent_usd

    # ---- structured call --------------------------------------------------
    def structured(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_schema: dict,
        max_tokens: int = 700,
        deep: bool = False,
        cache_system: bool = True,
        clock=time.monotonic,
        use_case: str | None = None,  # accepted for provider parity; Claude uses `deep`
        role: str | None = None,      # accepted for provider parity (Ollama role routing)
        model: str | None = None,     # manual override: exact Claude model id
    ) -> dict:
        """Force Claude to emit one tool call matching tool_schema; return its input.

        The system prompt is marked cacheable so repeated calls with the same system
        (same agent) reuse the cached prefix. `use_case` is ignored here (Claude
        selects model via `deep`); it is honored by the local Ollama client.
        """
        self._precheck(clock())
        # Manual model override wins; else deep -> opus, else default.
        model = model or (self.model_deep if deep else self.model)
        system_block = [{"type": "text", "text": system}]
        if cache_system:
            system_block[0]["cache_control"] = {"type": "ephemeral"}

        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_block,
            tools=[
                {
                    "name": tool_name,
                    "description": f"Return the {tool_name} result.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        self._account(model, resp.usage)
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return dict(block.input)
        raise RuntimeError("Claude did not return the expected tool call")
