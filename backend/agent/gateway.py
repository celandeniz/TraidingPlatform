"""Agent Gateway — a conversational front door over the platform's tools.

Natural language in -> intent classification -> dispatch to a read-only Toolset
method (positions, account, orders, signals, market data, fundamentals, search,
backtest) and optionally Vibe research -> natural-language answer out.

Deliberately READ-ONLY: the gateway never places orders. Trading stays on the
audited OMS path (Toolset.submit_order via /api/order or the gated Vibe
proposal route), not behind a chat box. Classification uses the LLM when
available and falls back to keyword routing so the gateway still works offline.
"""
from __future__ import annotations

from dataclasses import dataclass

# intent -> (Toolset method name, which args it consumes)
_TOOL_INTENTS = {
    "positions": ("list_positions", ()),
    "account": ("account_summary", ()),
    "orders": ("order_history", ("limit",)),
    "signals": ("recent_signals", ("limit",)),
    "market_data": ("get_market_data", ("symbol", "timeframe")),
    "fundamentals": ("get_fundamentals", ("symbol",)),
    "search": ("search_symbols", ("query",)),
    "backtest": ("run_backtest", ("symbol", "timeframe", "strategy")),
}
_INTENTS = list(_TOOL_INTENTS) + ["research", "help"]

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": _INTENTS},
        "symbol": {"type": "string"},
        "query": {"type": "string"},
        "timeframe": {"type": "string"},
        "strategy": {"type": "string"},
        "limit": {"type": "integer"},
    },
    "required": ["intent"],
}

# substring -> intent, for the no-LLM keyword fallback (first match wins).
_KEYWORDS = [
    ("position", "positions"), ("exposure", "positions"), ("holding", "positions"),
    ("account", "account"), ("balance", "account"), ("buying power", "account"),
    ("order", "orders"), ("fill", "orders"),
    ("signal", "signals"),
    ("fundamental", "fundamentals"), ("valuation", "fundamentals"), ("p/e", "fundamentals"),
    ("backtest", "backtest"),
    ("research", "research"), ("thesis", "research"), ("analy", "research"),
    ("search", "search"), ("find ", "search"), ("ticker", "search"),
    ("price", "market_data"), ("quote", "market_data"), ("bars", "market_data"),
    ("help", "help"), ("what can you", "help"),
]


@dataclass
class GatewayReply:
    ok: bool
    intent: str
    answer: str
    data: dict

    def as_dict(self) -> dict:
        return {"ok": self.ok, "intent": self.intent, "answer": self.answer,
                "data": self.data, "source": "agent_gateway"}


class AgentGateway:
    def __init__(self, toolset, llm=None, *, vibe=None):
        self._ts = toolset
        self._llm = llm
        self._vibe = vibe

    # --- public -----------------------------------------------------------
    def route(self, message: str) -> GatewayReply:
        if not message or not message.strip():
            return GatewayReply(False, "help", self._help_text(), {})
        intent, args = self._classify(message)
        data = self._dispatch(intent, args)
        answer = self._summarize(message, intent, data)
        return GatewayReply(True, intent, answer, data)

    # --- classification ---------------------------------------------------
    def _classify(self, message: str) -> tuple[str, dict]:
        if self._llm is not None:
            try:
                resp = self._llm.structured(
                    system=("Classify the user's trading-app request into one intent "
                            "and extract any symbol/query/timeframe/strategy/limit. "
                            "Intents: " + ", ".join(_INTENTS) + "."),
                    user=message, tool_name="route", tool_schema=_INTENT_SCHEMA,
                    max_tokens=200, use_case="fast",
                )
                if isinstance(resp, dict) and resp.get("intent") in _INTENTS:
                    return resp["intent"], resp
            except Exception:  # noqa: BLE001 - fall back to keywords
                pass
        return self._keyword_intent(message), self._keyword_args(message)

    def _keyword_intent(self, message: str) -> str:
        low = message.lower()
        for needle, intent in _KEYWORDS:
            if needle in low:
                return intent
        return "help"

    def _keyword_args(self, message: str) -> dict:
        # crude symbol grab: a 1-5 char all-caps token.
        sym = ""
        for tok in message.replace("?", " ").replace(",", " ").split():
            if 1 <= len(tok) <= 5 and tok.isupper() and tok.isalpha():
                sym = tok
                break
        return {"symbol": sym, "query": sym or message}

    # --- dispatch ---------------------------------------------------------
    def _dispatch(self, intent: str, args: dict) -> dict:
        if intent == "help":
            return {"ok": True, "capabilities": _INTENTS}
        if intent == "research":
            return self._research(args)
        spec = _TOOL_INTENTS.get(intent)
        if spec is None:
            return {"ok": False, "detail": f"unknown intent: {intent}"}
        method_name, arg_names = spec
        method = getattr(self._ts, method_name, None)
        if method is None:
            return {"ok": False, "detail": f"tool {method_name} unavailable"}
        kwargs = {k: args[k] for k in arg_names if args.get(k) not in (None, "")}
        try:
            return method(**kwargs)
        except Exception as exc:  # noqa: BLE001 - never crash the gateway
            return {"ok": False, "detail": f"{method_name} failed: {exc}"}

    def _research(self, args: dict) -> dict:
        if self._vibe is None:
            return {"ok": False, "detail": "research unavailable (Vibe sidecar off)"}
        from ..integrations.vibe_trading import research_adapter as vr

        sym = (args.get("symbol") or args.get("query") or "").upper()
        if not sym:
            return {"ok": False, "detail": "research needs a symbol"}
        return vr.run_research(self._vibe, sym).as_dict()

    # --- answer -----------------------------------------------------------
    def _summarize(self, message: str, intent: str, data: dict) -> str:
        if intent == "help":
            return self._help_text()
        if not data.get("ok", True):
            return data.get("detail", "Sorry, that didn't work.")
        if self._llm is not None:
            try:
                import json as _j

                resp = self._llm.structured(
                    system=("Answer the user's question in 1-3 sentences using ONLY the "
                            "tool result JSON. Be concrete; no advice."),
                    user=f"Question: {message}\nTool result: {_j.dumps(data, default=str)[:3000]}",
                    tool_name="answer",
                    tool_schema={"type": "object",
                                 "properties": {"answer": {"type": "string"}},
                                 "required": ["answer"]},
                    max_tokens=300, use_case="fast",
                )
                if isinstance(resp, dict) and resp.get("answer"):
                    return resp["answer"]
            except Exception:  # noqa: BLE001 - fall back to template
                pass
        return f"[{intent}] " + ", ".join(
            f"{k}={data[k]}" for k in list(data)[:6] if k != "ok")

    def _help_text(self) -> str:
        return ("I can answer questions about your platform: positions, account, "
                "orders, recent signals, market data, fundamentals, symbol search, "
                "backtests, and Vibe research. I do not place trades.")
