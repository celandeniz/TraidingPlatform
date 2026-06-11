"""PEAD: big positive earnings gap + volume -> ride the drift ~20 days."""
from __future__ import annotations

import pandas as pd

from backend.strategy.earnings_drift import generate


def _daily(n: int = 60, gap_at: int | None = None, gap_pct: float = 8.0,
           vol_mult_on_gap: float = 3.0) -> pd.DataFrame:
    idx = pd.bdate_range("2026-03-02", periods=n, tz="UTC")
    close, open_, vol = [], [], []
    px = 100.0
    for i in range(n):
        o = px
        if gap_at is not None and i == gap_at:
            o = px * (1 + gap_pct / 100.0)
        px = o
        open_.append(o); close.append(px)
        vol.append(1e6 * (vol_mult_on_gap if i == gap_at else 1.0))
    return pd.DataFrame({"open": open_, "high": [c * 1.01 for c in close],
                         "low": [c * 0.99 for c in close], "close": close,
                         "volume": vol}, index=idx)


def test_earnings_gap_up_fires_buy_with_hold_exits():
    df = _daily(n=40, gap_at=39)
    earn = [df.index[39].tz_localize(None).normalize()]
    sig = generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                   hold_days=20, stop_pct=10.0)
    assert sig["buy"] is True
    assert sig["time_stop_bars"] == 20
    assert sig["stop_loss_pct"] == 10.0


def test_gap_without_earnings_date_no_signal():
    df = _daily(n=40, gap_at=39)
    assert generate(df, earnings_dates=[], gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False


def test_small_gap_no_signal():
    df = _daily(n=40, gap_at=39, gap_pct=2.0)
    earn = [df.index[39].tz_localize(None).normalize()]
    assert generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False


def test_low_volume_gap_no_signal():
    df = _daily(n=40, gap_at=39, vol_mult_on_gap=1.0)
    earn = [df.index[39].tz_localize(None).normalize()]
    assert generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                    hold_days=20, stop_pct=10.0)["buy"] is False
