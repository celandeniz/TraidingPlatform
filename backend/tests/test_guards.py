"""Guard pipeline tests — no network (uses MockBroker)."""
from datetime import datetime, timedelta, timezone

from backend.execution.base import OrderRequest
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.portfolio.guards import (
    CooldownGuard,
    GuardPipeline,
    SymbolWhitelistGuard,
    build_guard_pipeline,
)


def _mock():
    b = MockExecutionAdapter(starting_cash=100_000)
    for s in ("AAPL", "MSFT", "TSLA"):
        b.mark(s, 100)
    return b


def test_whitelist_blocks_off_list_symbol():
    pipe = GuardPipeline(_mock(), [SymbolWhitelistGuard(["AAPL", "MSFT"])])
    ok = pipe.submit(OrderRequest("AAPL", "buy", 1))
    blocked = pipe.submit(OrderRequest("TSLA", "buy", 1))
    assert ok.ok
    assert not blocked.ok and blocked.status == "blocked" and "whitelist" in blocked.detail


def test_empty_whitelist_allows_all():
    pipe = GuardPipeline(_mock(), [SymbolWhitelistGuard([])])
    assert pipe.submit(OrderRequest("TSLA", "buy", 1)).ok


def test_cooldown_blocks_rapid_reentry_then_allows():
    t = {"now": datetime(2024, 1, 1, tzinfo=timezone.utc)}
    cd = CooldownGuard(60, clock=lambda: t["now"])
    pipe = GuardPipeline(_mock(), [cd])
    assert pipe.submit(OrderRequest("AAPL", "buy", 1)).ok        # first open records time
    assert not pipe.submit(OrderRequest("AAPL", "buy", 1)).ok    # 0s later -> blocked
    t["now"] += timedelta(seconds=61)
    assert pipe.submit(OrderRequest("AAPL", "buy", 1)).ok        # cooldown elapsed


def test_reduce_only_bypasses_guards():
    pipe = GuardPipeline(_mock(), [SymbolWhitelistGuard(["NONE"])])
    # opening TSLA blocked, but a reduce_only sell passes the guard layer
    assert not pipe.submit(OrderRequest("TSLA", "buy", 1)).ok
    # open a position directly on the broker, then close via the pipeline
    pipe._inner.submit(OrderRequest("TSLA", "buy", 5))
    closing = pipe.submit(OrderRequest("TSLA", "sell", 5, reduce_only=True))
    assert closing.ok  # bypassed whitelist


def test_build_pipeline_disabled_is_noop():
    inner = _mock()
    assert build_guard_pipeline(inner, {"guards": {"enabled": False}}) is inner
    assert build_guard_pipeline(inner, {}) is inner


def test_build_pipeline_assembles_from_config():
    inner = _mock()
    cfg = {"guards": {"enabled": True, "symbol_whitelist": ["AAPL"],
                      "cooldown_seconds": 30}}
    pipe = build_guard_pipeline(inner, cfg)
    assert isinstance(pipe, GuardPipeline)
    names = {g.name for g in pipe.guards}
    assert names == {"symbol_whitelist", "cooldown"}


def test_guard_pipeline_stacks_with_risk_manager():
    from backend.portfolio.risk import RiskConfig, RiskManager

    inner = _mock()
    risk = RiskManager(inner, RiskConfig(enabled=True, max_concurrent_positions=5))
    pipe = GuardPipeline(risk, [SymbolWhitelistGuard(["AAPL"])])
    # both layers satisfied -> fills; whitelist alone would block TSLA
    assert pipe.submit(OrderRequest("AAPL", "buy", 1)).ok
    assert not pipe.submit(OrderRequest("TSLA", "buy", 1)).ok
