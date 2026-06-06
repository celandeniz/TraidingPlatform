"""AutoTrader tests — no network (fake LLM + MockBroker toolset)."""
from datetime import datetime, timezone

from backend.agent.auto_trader import AutoTrader
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.mcp.tools import Toolset
from backend.oms.ledger import OrderManager

UTC = timezone.utc


class _FakeLLM:
    def __init__(self, actions):
        self._actions = actions

    def structured(self, **kw):
        return {"actions": self._actions}


def _trader(tmp_path, actions, cfg):
    broker = MockExecutionAdapter(starting_cash=100_000)
    for s in ("AAPL", "MSFT", "TSLA"):
        broker.mark(s, 100)
    oms = OrderManager(broker, ledger_path=tmp_path / "led.jsonl")
    ts = Toolset(broker, oms=oms, market_data=None, config={})
    at = AutoTrader(ts, _FakeLLM(actions), cfg, clock=lambda: datetime(2024, 1, 1, tzinfo=UTC),
                    store_path=tmp_path / "auto.jsonl")
    return at, broker


def test_disabled_does_nothing(tmp_path):
    at, broker = _trader(tmp_path, [{"symbol": "AAPL", "action": "buy", "qty": 1,
                                     "confidence": 0.9}], {"enabled": False})
    out = at.run_cycle()
    assert out["ran"] is False and broker.list_positions() == []


def test_dry_run_proposes_without_trading(tmp_path):
    at, broker = _trader(tmp_path, [{"symbol": "AAPL", "action": "buy", "qty": 2,
                                     "confidence": 0.9, "reason": "edge"}],
                         {"enabled": True, "dry_run": True, "min_confidence": 0.6})
    out = at.run_cycle()
    assert out["ran"] and out["actions"][0]["status"] == "proposed"
    assert broker.list_positions() == []  # nothing actually traded


def test_live_executes_through_toolset(tmp_path):
    at, broker = _trader(tmp_path, [{"symbol": "AAPL", "action": "buy", "qty": 2,
                                     "confidence": 0.9}],
                         {"enabled": True, "dry_run": False, "min_confidence": 0.6})
    out = at.run_cycle()
    assert out["actions"][0]["status"] == "executed"
    assert broker.list_positions()[0]["symbol"] == "AAPL"


def test_filters_low_confidence_and_offlist_and_hold(tmp_path):
    actions = [
        {"symbol": "AAPL", "action": "buy", "qty": 1, "confidence": 0.3},   # low conf
        {"symbol": "TSLA", "action": "buy", "qty": 1, "confidence": 0.9},   # off-list
        {"symbol": "MSFT", "action": "hold", "qty": 1, "confidence": 0.9},  # not actionable
        {"symbol": "AAPL", "action": "buy", "qty": 1, "confidence": 0.9},   # OK
    ]
    cfg = {"enabled": True, "dry_run": True, "min_confidence": 0.6,
           "symbol_whitelist": ["AAPL"]}
    at, _ = _trader(tmp_path, actions, cfg)
    out = at.run_cycle()
    statuses = [(a["symbol"], a["action"], a["status"]) for a in out["actions"]]
    proposed = [s for s in statuses if s[2] == "proposed"]
    assert proposed == [("AAPL", "buy", "proposed")]  # only the valid one


def test_max_actions_cap(tmp_path):
    actions = [{"symbol": "AAPL", "action": "buy", "qty": 1, "confidence": 0.9}] * 5
    cfg = {"enabled": True, "dry_run": True, "min_confidence": 0.6, "max_actions_per_cycle": 2}
    at, _ = _trader(tmp_path, actions, cfg)
    out = at.run_cycle()
    assert sum(1 for a in out["actions"] if a["status"] == "proposed") == 2


def test_seed_candidates_injected_into_context(tmp_path):
    # Scanner candidates passed to run_cycle should reach the LLM context.
    seen = {}

    class _CapturingLLM:
        def structured(self, *, user, **kw):
            seen["user"] = user
            return {"actions": []}

    broker = MockExecutionAdapter(starting_cash=100_000)
    broker.mark("AAPL", 100)
    oms = OrderManager(broker, ledger_path=tmp_path / "led.jsonl")
    ts = Toolset(broker, oms=oms, market_data=None, config={})
    at = AutoTrader(ts, _CapturingLLM(), {"enabled": True, "dry_run": True},
                    store_path=tmp_path / "auto.jsonl")
    at.run_cycle(seed_candidates=[{"symbol": "NVDA", "score": 88}])
    assert "scanner_candidates" in seen["user"] and "NVDA" in seen["user"]


def test_qty_capped_at_max(tmp_path):
    at, _ = _trader(tmp_path, [{"symbol": "AAPL", "action": "buy", "qty": 999,
                                "confidence": 0.9}],
                    {"enabled": True, "dry_run": True, "min_confidence": 0.6, "max_qty": 5})
    out = at.run_cycle()
    assert out["actions"][0]["qty"] == 5
