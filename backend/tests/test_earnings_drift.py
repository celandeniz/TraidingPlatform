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


def test_friday_amc_monday_reaction_fires():
    # n=41, gap_at=40: bdate_range("2026-03-02") -> idx[40] = 2026-04-27 (Monday, weekday=0)
    # earnings date = idx[40] - 3 calendar days = 2026-04-24 (Friday, weekday=4)
    # calendar diff = 3  -> fails old match_days=1 calendar check
    # business diff  = 1 -> passes new business-day check
    df = _daily(n=41, gap_at=40)
    assert df.index[40].weekday() == 0, "gap day must be Monday"
    earn_friday = df.index[40] - pd.Timedelta(days=3)
    assert earn_friday.weekday() == 4, "earnings date must be Friday"
    earn = [earn_friday.tz_localize(None).normalize()]
    sig = generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                   hold_days=20, stop_pct=10.0, match_days=1)
    assert sig["buy"] is True, (
        "Friday AMC earnings should fire on the following Monday with match_days=1 (business days)"
    )


def test_negative_gap_short_fires_when_allowed():
    # gap_pct=-8.0 (gap down), earnings on the gap day
    df = _daily(n=40, gap_at=39, gap_pct=-8.0)
    earn = [df.index[39].tz_localize(None).normalize()]
    sig_short = generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                         hold_days=20, stop_pct=10.0, allow_short=True)
    assert sig_short["sell"] is True, "negative gap with allow_short=True must fire sell"
    assert "stop_loss_pct" in sig_short
    assert "time_stop_bars" in sig_short

    sig_no_short = generate(df, earnings_dates=earn, gap_min_pct=5.0, vol_mult=1.5,
                            hold_days=20, stop_pct=10.0, allow_short=False)
    assert sig_no_short["sell"] is False, "negative gap with allow_short=False must NOT fire sell"
