"""Vibe execution-routing guard tests.

The load-bearing safety properties for letting Vibe PROPOSE orders:
  1. A valid proposal reaches the OMS path (stage->commit->push->adapter.submit),
     not a broker directly.
  2. execution_router.py cannot reach live trading: it imports neither
     backend.execution.live nor any executor (static AST scan).
  3. Malformed proposals are rejected BEFORE any submit.
"""
import ast
import pathlib

import pytest

from backend.execution.base import OrderResult
from backend.integrations.vibe_trading import execution_router
from backend.integrations.vibe_trading.schemas import VibeOrderProposal
from backend.mcp.tools import Toolset


class RecordingExecutor:
    """Stands in for the real ExecutionAdapter; records submitted requests."""
    def __init__(self):
        self.submitted = []

    def submit(self, req) -> OrderResult:
        self.submitted.append(req)
        return OrderResult(ok=True, order_id="x1", symbol=req.symbol, side=req.side,
                           qty=req.qty, status="filled")


def _toolset_with_oms():
    from backend.oms.ledger import OrderManager
    execu = RecordingExecutor()
    oms = OrderManager(execu)
    return Toolset(execu, oms=oms, config={}), execu


# --- 1. valid proposal reaches the OMS/adapter path -----------------------
def test_valid_proposal_reaches_oms_submit():
    toolset, execu = _toolset_with_oms()
    out = execution_router.route_proposal(
        {"symbol": "aapl", "side": "long", "qty": 3, "rationale": "breakout"}, toolset)
    assert out["ok"] is True and out["source"] == "vibe"
    assert len(execu.submitted) == 1
    req = execu.submitted[0]
    assert req.symbol == "AAPL" and req.side == "buy" and req.qty == 3


def test_short_maps_to_sell():
    toolset, execu = _toolset_with_oms()
    execution_router.route_proposal({"ticker": "TSLA", "action": "short", "size": 2}, toolset)
    assert execu.submitted[0].side == "sell"


# --- 2. static guard: router can never reach live trading -----------------
def test_router_does_not_import_live_or_executors():
    src = pathlib.Path(execution_router.__file__).read_text()
    tree = ast.parse(src)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    joined = " ".join(imported)
    assert "execution.live" not in joined and "execution" not in joined
    assert "brokers" not in joined and "build_live_executor" not in src


# --- 3. malformed proposals rejected before any submit --------------------
class _Spy:
    def __init__(self):
        self.calls = 0

    def submit_order(self, *a, **k):
        self.calls += 1
        return {"ok": True}


@pytest.mark.parametrize("bad", [
    {"side": "buy", "qty": 1},                 # missing symbol
    {"symbol": "AAPL", "qty": 1},              # missing/!directional side
    {"symbol": "AAPL", "side": "hold", "qty": 1},  # unrecognized side
    {"symbol": "AAPL", "side": "buy", "qty": 0},   # non-positive qty
    {"symbol": "AAPL", "side": "buy", "qty": -5},  # negative qty
    {"symbol": "AAPL", "side": "buy"},         # missing qty
    "not-a-dict",                              # wrong type
])
def test_malformed_rejected_before_submit(bad):
    spy = _Spy()
    out = execution_router.route_proposal(bad, spy)
    assert out["ok"] is False and out["stage"] == "validation"
    assert spy.calls == 0


def test_qty_string_coerced():
    assert VibeOrderProposal.from_vibe_dict(
        {"symbol": "AAPL", "side": "buy", "qty": "4"}).qty == 4.0


def test_bool_qty_rejected():
    with pytest.raises(ValueError):
        VibeOrderProposal.from_vibe_dict({"symbol": "AAPL", "side": "buy", "qty": True})
