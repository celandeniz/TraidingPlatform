"""Execution analytics / TCA tests — no network."""
from backend.execution.analytics import ExecutionAnalytics, slippage_bps
from backend.execution.base import OrderRequest, OrderResult
from backend.execution.fills import FillModelConfig
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.oms.ledger import OrderManager


def test_slippage_sign_is_adverse():
    # buy filled above arrival -> positive (paid up); sell below arrival -> positive too
    assert slippage_bps(100, 100.1, "buy") > 0
    assert slippage_bps(100, 99.9, "sell") > 0
    assert slippage_bps(100, 99.9, "buy") < 0   # bought cheaper = favorable


def test_record_computes_bps_and_writes(tmp_path):
    an = ExecutionAnalytics(path=tmp_path / "tca.jsonl")
    res = OrderResult(ok=True, order_id="1", symbol="AAPL", side="buy", qty=10,
                      status="filled", filled_qty=10, fill_price=100.3)
    rep = an.record(res, arrival_price=100.0)
    assert round(rep.slippage_bps, 1) == 30.0  # 0.3% = 30 bps adverse
    assert rep.fill_ratio == 1.0
    assert an.summary()["n"] == 1


def test_partial_fill_ratio(tmp_path):
    an = ExecutionAnalytics(path=tmp_path / "tca.jsonl")
    res = OrderResult(ok=True, order_id="2", symbol="X", side="buy", qty=100,
                      status="partial", filled_qty=25, fill_price=10.0)
    rep = an.record(res, arrival_price=10.0)
    assert rep.fill_ratio == 0.25


def test_oms_push_records_tca(tmp_path):
    broker = MockExecutionAdapter(realistic=True,
                                  fill_config=FillModelConfig(spread_bps=4, base_slippage_bps=0,
                                                              impact_coef_bps=0, commission_bps=0))
    broker.mark("AAPL", 100)
    an = ExecutionAnalytics(path=tmp_path / "tca.jsonl")
    oms = OrderManager(broker, ledger_path=tmp_path / "led.jsonl", analytics=an)
    # arrival = 100 (meta), fill includes half-spread(2bps) -> ~100.02 -> ~2 bps slippage
    oms.stage_commit_push(OrderRequest("AAPL", "buy", 1, meta={"arrival": 100.0}),
                          message="tca")
    s = an.summary()
    assert s["n"] == 1 and round(s["avg_slippage_bps"], 1) == 2.0
