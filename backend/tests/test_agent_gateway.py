"""Agent Gateway tests — fake Toolset / LLM, no network."""
from backend.agent.gateway import AgentGateway


class FakeToolset:
    def __init__(self):
        self.calls = []

    def list_positions(self):
        self.calls.append(("list_positions", {}))
        return {"ok": True, "positions": [{"symbol": "AAPL", "qty": 10}]}

    def account_summary(self):
        self.calls.append(("account_summary", {}))
        return {"ok": True, "account": {"equity": 100000}}

    def order_history(self, limit=50):
        self.calls.append(("order_history", {"limit": limit}))
        return {"ok": True, "orders": []}

    def get_fundamentals(self, symbol):
        self.calls.append(("get_fundamentals", {"symbol": symbol}))
        return {"ok": True, "symbol": symbol, "pe": 30}

    def run_backtest(self, symbol, timeframe="5m", strategy="spike_fade"):
        self.calls.append(("run_backtest", {"symbol": symbol, "strategy": strategy}))
        return {"ok": True, "symbol": symbol, "n_trades": 12}

    def search_symbols(self, query):
        self.calls.append(("search_symbols", {"query": query}))
        return {"ok": True, "matches": [query]}

    def get_market_data(self, symbol, timeframe="1d"):
        self.calls.append(("get_market_data", {"symbol": symbol}))
        return {"ok": True, "symbol": symbol, "bars": 100}

    def recent_signals(self, limit=20):
        self.calls.append(("recent_signals", {"limit": limit}))
        return {"ok": True, "signals": []}


class FakeLLM:
    """Returns a fixed intent for classification, and an answer for summarize."""
    def __init__(self, intent="positions", symbol=""):
        self._intent = intent
        self._symbol = symbol

    def structured(self, *, tool_name, **kw):
        if tool_name == "route":
            out = {"intent": self._intent}
            if self._symbol:
                out["symbol"] = self._symbol
            return out
        return {"answer": "Here is your summary."}


# --- keyword fallback (no LLM) --------------------------------------------
def test_keyword_positions():
    ts = FakeToolset()
    reply = AgentGateway(ts, llm=None).route("what's my exposure?")
    assert reply.intent == "positions"
    assert ts.calls[0][0] == "list_positions"
    assert reply.as_dict()["source"] == "agent_gateway"


def test_keyword_fundamentals_with_symbol():
    ts = FakeToolset()
    reply = AgentGateway(ts, llm=None).route("show fundamentals for AAPL")
    assert reply.intent == "fundamentals"
    assert ts.calls[0] == ("get_fundamentals", {"symbol": "AAPL"})


def test_help_when_unmatched():
    reply = AgentGateway(FakeToolset(), llm=None).route("hello there")
    assert reply.intent == "help" and "positions" in reply.answer


def test_empty_message_is_help():
    reply = AgentGateway(FakeToolset(), llm=None).route("   ")
    assert reply.intent == "help" and reply.ok is False


# --- LLM-driven classification --------------------------------------------
def test_llm_intent_and_summary():
    ts = FakeToolset()
    gw = AgentGateway(ts, llm=FakeLLM(intent="account"))
    reply = gw.route("how much cash do I have?")
    assert reply.intent == "account"
    assert ts.calls[0][0] == "account_summary"
    assert reply.answer == "Here is your summary."


def test_llm_backtest_args():
    ts = FakeToolset()
    gw = AgentGateway(ts, llm=FakeLLM(intent="backtest", symbol="MSFT"))
    reply = gw.route("backtest MSFT")
    assert reply.intent == "backtest"
    assert ts.calls[0] == ("run_backtest", {"symbol": "MSFT", "strategy": "spike_fade"})


# --- gateway never trades -------------------------------------------------
def test_gateway_has_no_submit_intent():
    from backend.agent import gateway as gw_mod
    assert "submit_order" not in gw_mod._TOOL_INTENTS.values().__str__()
    assert all("submit" not in i for i in gw_mod._INTENTS)


# --- research routes to vibe when present ---------------------------------
class FakeVibe:
    pass


def test_research_without_vibe_degrades():
    reply = AgentGateway(FakeToolset(), llm=FakeLLM(intent="research", symbol="AAPL")).route(
        "research AAPL")
    assert reply.intent == "research" and not reply.ok  # ok mirrors tool result
    assert reply.data["ok"] is False  # vibe off


def test_tool_failure_degrades_gracefully():
    class Broken(FakeToolset):
        def account_summary(self):
            raise RuntimeError("boom")

    reply = AgentGateway(Broken(), llm=FakeLLM(intent="account")).route("account?")
    assert not reply.ok and reply.data["ok"] is False and "boom" in reply.answer
