"""Routing tests — no network (uses fake adapters)."""
from backend.brokers import RoutingExecutionAdapter, resolve_asset_class
from backend.execution.base import OrderRequest, OrderResult, PositionView


def test_resolve_asset_class_pair_is_crypto():
    cfg = {"brokers": {"default_asset_class": "equity", "symbol_overrides": {}}}
    assert resolve_asset_class("BTC/USDT", cfg) == "crypto"
    assert resolve_asset_class("AAPL", cfg) == "equity"


def test_resolve_asset_class_override_wins():
    cfg = {"brokers": {"default_asset_class": "equity",
                       "symbol_overrides": {"WEIRD": "crypto"}}}
    assert resolve_asset_class("WEIRD", cfg) == "crypto"


class _Fake:
    def __init__(self, tag):
        self.tag = tag
        self.calls = []

    def submit(self, req):
        self.calls.append(req)
        return OrderResult(True, f"{self.tag}-1", req.symbol, req.side, req.qty, "ok")

    def list_positions(self):
        return [PositionView(symbol=self.tag, qty=1, side="long", avg_entry=1.0,
                             current=1.0, unrealized_pl=0.0, unrealized_plpc=0.0)]

    def account_summary(self):
        return {"equity": 100.0, "cash": 100.0}


def test_routing_fans_out_by_asset_class():
    eq, cr = _Fake("eq"), _Fake("cr")
    router = RoutingExecutionAdapter({"equity": eq, "crypto": cr})
    router.submit(OrderRequest("AAPL", "buy", 1, asset_class="equity"))
    router.submit(OrderRequest("BTC/USDT", "sell", 1, asset_class="crypto"))
    assert len(eq.calls) == 1 and len(cr.calls) == 1
    assert eq.calls[0].symbol == "AAPL"
    assert cr.calls[0].symbol == "BTC/USDT"


def test_routing_merges_positions_and_accounts():
    router = RoutingExecutionAdapter({"equity": _Fake("eq"), "crypto": _Fake("cr")})
    positions = router.list_positions()
    assert {p["symbol"] for p in positions} == {"eq", "cr"}
    acct = router.account_summary()
    assert acct["equity"] == 200.0  # summed across both brokers
    assert "by_broker" in acct


def test_routing_unknown_asset_class_rejects():
    router = RoutingExecutionAdapter({"equity": _Fake("eq")})
    r = router.submit(OrderRequest("BTC/USDT", "buy", 1, asset_class="crypto"))
    assert not r.ok and "no executor" in r.detail


def test_build_executor_mock_is_networkfree():
    from backend.brokers import build_executor
    from backend.execution.mock_adapter import MockExecutionAdapter

    cfg = {"brokers": {"executor": "mock", "mock": {"starting_cash": 5000}}}
    ex = build_executor("equity", settings=None, cfg=cfg)
    assert isinstance(ex, MockExecutionAdapter)
    assert ex.account_summary()["cash"] == 5000


def test_build_executor_per_asset_class_override():
    from backend.brokers import build_executor
    from backend.execution.mock_adapter import MockExecutionAdapter

    # crypto overridden to mock; equity would still build the default (not exercised here)
    cfg = {"brokers": {"crypto": {"executor": "mock"}}}
    ex = build_executor("crypto", settings=None, cfg=cfg)
    assert isinstance(ex, MockExecutionAdapter)
