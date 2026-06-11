"""xs_momentum + sector_rotation rebalance logic on synthetic daily frames."""
import pandas as pd

from backend.strategy.base import UniverseContext
from backend.strategy.sector_rotation import SectorRotationStrategy
from backend.strategy.xs_momentum import XsMomentumStrategy


def _frame(total_ret: float, n: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    r = (1 + total_ret) ** (1 / (n - 1)) - 1
    px = pd.Series([100.0 * (1 + r) ** i for i in range(n)], index=idx)
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 1e6})


def _ctx(frames, config):
    last = max(f.index.max() for f in frames.values())
    return UniverseContext(date=last, frames=frames, config=config)


def test_xs_momentum_picks_strongest_equal_weight():
    frames = {"HOT": _frame(0.9), "WARM": _frame(0.4), "COLD": _frame(-0.3),
              "SPY": _frame(0.2)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 2, "regime_filter": False}}))
    assert set(w) == {"HOT", "WARM"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["HOT"] - 0.5) < 1e-9


def test_xs_momentum_goes_cash_when_spy_below_200dma():
    # SPY trending down -> price below its 200-day MA -> all cash
    frames = {"HOT": _frame(0.9), "SPY": _frame(-0.4)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 1, "regime_filter": True}}))
    assert w == {}


def test_xs_momentum_skips_short_history_symbols():
    frames = {"HOT": _frame(0.9), "NEW": _frame(5.0, n=60), "SPY": _frame(0.2)}
    s = XsMomentumStrategy()
    w = s.rebalance(_ctx(frames, {"xs_momentum": {"top_n": 1, "regime_filter": False}}))
    assert "NEW" not in w and "HOT" in w


def test_sector_rotation_top3_blended():
    frames = {f"X{i}": _frame(0.05 * i) for i in range(1, 12)}  # X11 strongest
    frames["SPY"] = _frame(0.2)
    s = SectorRotationStrategy()
    w = s.rebalance(_ctx(frames, {"sector_rotation": {
        "etfs": [f"X{i}" for i in range(1, 12)], "top_n": 3, "regime_filter": False}}))
    assert set(w) == {"X11", "X10", "X9"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
