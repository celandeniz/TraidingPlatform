"""OMS / order-ledger tests — no network (MockBroker + temp ledger file)."""
import pytest

from backend.execution.base import OrderRequest
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.oms.ledger import OrderManager


def _mgr(tmp_path):
    b = MockExecutionAdapter(starting_cash=100_000)
    b.mark("AAPL", 100)
    return OrderManager(b, ledger_path=tmp_path / "order_ledger.jsonl"), b


def test_stage_commit_push_fills_and_records_history(tmp_path):
    mgr, broker = _mgr(tmp_path)
    oid = mgr.stage(OrderRequest("AAPL", "buy", 10), note="entry on signal")
    assert mgr.get(oid).state == "staged"
    mgr.commit(oid, "confirmed by committee")
    assert mgr.get(oid).state == "committed"
    res = mgr.push(oid)
    assert res.ok
    rec = mgr.get(oid)
    assert rec.state == "filled" and rec.message == "confirmed by committee"
    states = [h["state"] for h in rec.history]
    assert states == ["staged", "committed", "pushed", "filled"]
    assert broker.list_positions()[0]["qty"] == 10  # push actually executed


def test_cannot_push_uncommitted(tmp_path):
    mgr, _ = _mgr(tmp_path)
    oid = mgr.stage(OrderRequest("AAPL", "buy", 1))
    with pytest.raises(ValueError):
        mgr.push(oid)  # still staged, not committed


def test_discard_and_open_orders(tmp_path):
    mgr, _ = _mgr(tmp_path)
    a = mgr.stage(OrderRequest("AAPL", "buy", 1))
    b = mgr.stage(OrderRequest("AAPL", "buy", 2))
    mgr.commit(a, "ok")
    assert {r.id for r in mgr.open_orders()} == {a, b}
    mgr.discard(b, "changed mind")
    assert {r.id for r in mgr.open_orders()} == {a}
    assert mgr.get(b).state == "discarded"


def test_rejected_push_is_recorded(tmp_path):
    b = MockExecutionAdapter()  # no mark -> fills rejected ("no price")
    mgr = OrderManager(b, ledger_path=tmp_path / "l.jsonl")
    oid = mgr.stage(OrderRequest("AAPL", "buy", 1))
    mgr.commit(oid, "go")
    res = mgr.push(oid)
    assert not res.ok and mgr.get(oid).state == "rejected"


def test_ledger_replays_state_across_restart(tmp_path):
    path = tmp_path / "order_ledger.jsonl"
    mgr, _ = _mgr(tmp_path)
    oid = mgr.stage_commit_push(OrderRequest("AAPL", "buy", 5), message="auto")
    assert oid.ok
    # new manager over the SAME ledger file rebuilds history from disk
    fresh = OrderManager(MockExecutionAdapter(), ledger_path=path)
    recs = fresh.history()
    assert len(recs) == 1 and recs[0].state == "filled" and recs[0].message == "auto"
