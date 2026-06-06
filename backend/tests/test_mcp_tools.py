"""MCP Toolset tests — no network (MockBroker + OMS + temp ledger)."""
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.mcp.tools import Toolset
from backend.oms.ledger import OrderManager


def _toolset(tmp_path):
    b = MockExecutionAdapter(starting_cash=50_000)
    b.mark("AAPL", 100)
    oms = OrderManager(b, ledger_path=tmp_path / "ledger.jsonl")
    return Toolset(b, oms=oms, market_data=None, config={}), b


def test_submit_order_routes_through_oms_and_fills(tmp_path):
    ts, broker = _toolset(tmp_path)
    out = ts.submit_order("aapl", "buy", 10, message="mcp test")
    assert out["ok"] and out["status"] == "filled"
    assert broker.list_positions()[0]["qty"] == 10
    # the order is now auditable in history
    hist = ts.order_history()
    assert hist["ok"] and hist["orders"][-1]["state"] == "filled"
    assert hist["orders"][-1]["message"] == "mcp test"


def test_submit_order_bad_side_rejected(tmp_path):
    ts, _ = _toolset(tmp_path)
    assert ts.submit_order("AAPL", "hold", 1)["ok"] is False


def test_positions_and_account(tmp_path):
    ts, _ = _toolset(tmp_path)
    ts.submit_order("AAPL", "buy", 5)
    assert ts.list_positions()["positions"][0]["symbol"] == "AAPL"
    assert ts.account_summary()["account"]["status"] == "active"


def test_market_data_tools_degrade_without_provider(tmp_path):
    ts, _ = _toolset(tmp_path)
    assert ts.get_market_data("AAPL")["ok"] is False
    assert ts.get_fundamentals("AAPL")["ok"] is False
    assert ts.search_symbols("apple")["ok"] is False


def test_describe_lists_tools(tmp_path):
    ts, _ = _toolset(tmp_path)
    names = ts.describe()["tools"]
    assert "submit_order" in names and "run_backtest" in names and len(names) == 9
