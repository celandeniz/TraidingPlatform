"""Unit tests for the execution lifecycle (long AND short), no network."""
from datetime import datetime, timedelta, timezone

from backend.execution.base import OrderRequest, OrderResult
from backend.portfolio.calendar import CryptoCalendar, EquityCalendar
from backend.portfolio.exits import evaluate_exits
from backend.portfolio.manager import ExitConfig, PositionManager
from backend.portfolio.position import (
    Position, unrealized_pl, unrealized_pl_pct, update_high_water,
)
from backend.portfolio.risk import RiskConfig, RiskManager, position_size
from backend.research.base import Decision

UTC = timezone.utc


def _pos(side, entry=100.0, **kw):
    return Position(
        symbol="X", asset_class="equity", side=side, qty=10.0, avg_entry=entry,
        opened_at=datetime(2026, 5, 30, 14, 0, tzinfo=UTC),
        take_profit_pct=kw.get("tp", 1.5), stop_loss_pct=kw.get("sl", 1.0),
        trailing_stop_pct=kw.get("trail", None), time_stop_minutes=kw.get("time", None),
    )


# ---- P&L sign-awareness ---------------------------------------------------
def test_long_pl_positive_when_price_up():
    p = _pos("long")
    assert unrealized_pl(p, 110.0) == 100.0  # +10 * 10 shares
    assert abs(unrealized_pl_pct(p, 110.0) - 10.0) < 1e-9


def test_short_pl_positive_when_price_down():
    p = _pos("short")
    assert unrealized_pl(p, 90.0) == 100.0   # short gains when price falls
    assert abs(unrealized_pl_pct(p, 90.0) - 10.0) < 1e-9


def test_short_pl_negative_when_price_up():
    p = _pos("short")
    assert unrealized_pl(p, 110.0) == -100.0


# ---- exit rules -----------------------------------------------------------
def _now(p, minutes=0):
    return p.opened_at + timedelta(minutes=minutes)


def test_long_take_profit():
    p = _pos("long", tp=1.5)
    d = evaluate_exits(p, 101.6, _now(p))
    assert d.should_exit and d.reason == "take_profit"


def test_long_stop_loss():
    p = _pos("long", sl=1.0)
    d = evaluate_exits(p, 98.9, _now(p))
    assert d.should_exit and d.reason == "stop_loss"


def test_short_stop_loss_when_price_rises():
    p = _pos("short", sl=1.0)
    d = evaluate_exits(p, 101.5, _now(p))  # price up = loss for short
    assert d.should_exit and d.reason == "stop_loss"


def test_long_trailing_stop():
    p = _pos("long", sl=5.0, trail=0.8)
    update_high_water(p, 105.0)             # peak
    d = evaluate_exits(p, 104.0, _now(p))   # gave back ~0.95% from peak
    assert d.should_exit and d.reason == "trailing_stop"


def test_opposite_signal_closes():
    p = _pos("long")
    d = evaluate_exits(p, 100.0, _now(p), opposite_signal=True)
    assert d.should_exit and d.reason == "opposite_signal"


def test_eod_flat_closes():
    p = _pos("long")
    d = evaluate_exits(p, 100.0, _now(p), market_is_closing=True)
    assert d.should_exit and d.reason == "eod_flat"


def test_time_stop():
    p = _pos("long", time=30)
    d = evaluate_exits(p, 100.0, _now(p, 31))
    assert d.should_exit and d.reason == "time_stop"


def test_no_exit_when_flat():
    p = _pos("long", trail=0.8, time=120)
    d = evaluate_exits(p, 100.2, _now(p, 5))
    assert not d.should_exit


# ---- calendars ------------------------------------------------------------
def test_crypto_always_open():
    c = CryptoCalendar()
    assert c.is_open(datetime(2026, 5, 31, 3, 0, tzinfo=UTC))  # Sunday
    assert not c.is_closing_within(datetime(2026, 5, 31, 3, 0, tzinfo=UTC), 10)


def test_equity_closed_on_weekend():
    c = EquityCalendar()
    assert not c.is_open(datetime(2026, 5, 31, 17, 0, tzinfo=UTC))  # Sunday


def test_equity_open_midday_weekday():
    # 2026-06-01 is a Monday; 15:00 UTC = 11:00 ET (open)
    c = EquityCalendar()
    assert c.is_open(datetime(2026, 6, 1, 15, 0, tzinfo=UTC))


# ---- position sizing ------------------------------------------------------
def test_position_size_risk_based():
    # equity 10000, risk 1% = $100, stop distance $2 -> 50 units, under notional cap
    qty = position_size(10000, entry=100, stop=98, risk_pct=1.0, max_position_pct=100)
    assert abs(qty - 50.0) < 1e-9


def test_position_size_notional_capped():
    qty = position_size(10000, entry=100, stop=99.99, risk_pct=1.0, max_position_pct=20)
    # tiny stop -> huge risk_qty, capped by 20% notional = $2000/100 = 20 units
    assert abs(qty - 20.0) < 1e-9


# ---- RiskManager guards ---------------------------------------------------
class FakeAdapter:
    def __init__(self, positions=None):
        self._positions = positions or []
        self.submitted = []

    def submit(self, req):
        self.submitted.append(req)
        return OrderResult(True, "oid", req.symbol, req.side, req.qty, "accepted")

    def list_positions(self):
        return self._positions

    def account_summary(self):
        return {"equity": 10000.0, "cash": 10000.0}


def test_kill_switch_blocks_open_but_allows_close():
    inner = FakeAdapter()
    rm = RiskManager(inner, RiskConfig(max_daily_loss_pct=3.0))
    rm.engage_kill_switch("test")
    opened = rm.submit(OrderRequest("X", "buy", 1))
    assert not opened.ok and opened.status == "blocked"
    closed = rm.submit(OrderRequest("X", "sell", 1, reduce_only=True))
    assert closed.ok  # closing always allowed


def test_daily_loss_trips_kill_switch():
    rm = RiskManager(FakeAdapter(), RiskConfig(max_daily_loss_pct=3.0))
    rm.on_mark(10000.0)   # baseline
    rm.on_mark(9650.0)    # -3.5% -> trips
    assert rm.killed


def test_max_concurrent_positions_blocks():
    inner = FakeAdapter(positions=[{"symbol": "A"}, {"symbol": "B"}])
    rm = RiskManager(inner, RiskConfig(max_concurrent_positions=2))
    r = rm.submit(OrderRequest("C", "buy", 1))
    assert not r.ok and "concurrent" in r.detail


# ---- PositionManager open/manage round-trip -------------------------------
def _pm(executor, exit_cfg=None):
    t = [datetime(2026, 6, 1, 15, 0, tzinfo=UTC)]
    return PositionManager(
        executor, clock=lambda: t[0],
        market_is_closing=lambda now, m: False,
        exit_cfg=exit_cfg or ExitConfig(),
    ), t


def test_open_long_then_take_profit_closes():
    ex = FakeAdapter()
    pm, t = _pm(ex, ExitConfig(take_profit_pct=1.0, stop_loss_pct=2.0,
                               trailing_stop_pct=None, time_stop_minutes=None))
    d = Decision("X", "SPOT_LONG", "ALLOW", "buy", "r")
    opened = pm.open_from_decision(d, mark=100.0, qty=10)
    assert opened.ok and "X" in pm.positions
    # price rises 1.2% -> take profit
    closed = pm.manage("X", 101.2)
    assert closed.ok and "X" not in pm.positions
    assert ex.submitted[-1].reduce_only is True
    assert ex.submitted[-1].side == "sell"  # close a long


def test_open_short_then_stop_closes():
    ex = FakeAdapter()
    pm, t = _pm(ex, ExitConfig(take_profit_pct=5.0, stop_loss_pct=1.0,
                               trailing_stop_pct=None, time_stop_minutes=None))
    d = Decision("X", "SPOT_SHORT", "ALLOW", "sell", "r")
    pm.open_from_decision(d, mark=100.0, qty=10)
    assert pm.positions["X"].side == "short"
    closed = pm.manage("X", 101.5)  # price up = short loss -> stop
    assert closed.ok and "X" not in pm.positions
    assert ex.submitted[-1].side == "buy"  # close a short


def test_none_decision_opens_nothing():
    ex = FakeAdapter()
    pm, t = _pm(ex)
    assert pm.open_from_decision(Decision("X", "NONE", "ALLOW", None, "r"), 100.0, 10) is None
    assert not pm.positions
