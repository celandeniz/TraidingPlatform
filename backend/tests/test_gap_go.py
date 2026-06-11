"""Gap-and-Go: gap >= 2% over prior session close, holds above VWAP, breaks the
first-5-minute high. Prior session close is derived from the 1m window itself."""
from __future__ import annotations

import pandas as pd

from backend.strategy.gap_go import generate


def _two_days(day1_close: float, day2_closes: list[float]) -> pd.DataFrame:
    """Day 1: 30 flat 1m bars ending at day1_close. Day 2: 09:30 ET +."""
    i1 = pd.date_range("2026-06-08 15:30", periods=30, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    d1 = pd.DataFrame({"open": day1_close, "high": day1_close + 0.05,
                       "low": day1_close - 0.05, "close": day1_close,
                       "volume": 5_000.0}, index=i1)
    i2 = pd.date_range("2026-06-09 09:30", periods=len(day2_closes), freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series(day2_closes, index=i2)
    d2 = pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.05,
                       "low": c - 0.05, "close": c, "volume": 20_000.0})
    return pd.concat([d1, d2])


def test_gap_up_hold_above_vwap_break_5m_high_fires_buy():
    # prev close 100; opens 103 (3% gap); 5 bars 102.8..103.2; bar 6 breaks to 103.6
    df = _two_days(100.0, [103.0, 102.9, 103.0, 103.1, 103.2, 103.6])
    sig = generate(df, gap_min_pct=2.0, confirm_minutes=5)
    assert sig["buy"] is True
    assert sig["stop_loss_pct"] > 0          # stop at VWAP distance
    assert sig["time_stop_bars"] > 0


def test_no_gap_no_signal():
    df = _two_days(100.0, [100.4, 100.5, 100.6, 100.7, 100.8, 101.2])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_gap_fill_disqualifies():
    # gaps to 103 but trades back through prior close (100) -> dead gap, skip
    df = _two_days(100.0, [103.0, 101.0, 99.9, 103.0, 103.2, 103.6])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_below_vwap_disqualifies():
    # gap up then steady fade: last close below session VWAP
    df = _two_days(100.0, [103.0, 102.8, 102.5, 102.2, 102.0, 102.1])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_no_prior_session_no_signal():
    i2 = pd.date_range("2026-06-09 09:30", periods=6, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series([103.0, 102.9, 103.0, 103.1, 103.2, 103.6], index=i2)
    df = pd.DataFrame({"open": c, "high": c + 0.05, "low": c - 0.05,
                       "close": c, "volume": 1000.0})
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False


def test_window_missing_session_open_no_signal():
    """Rolling window that starts mid-day (10:01 ET) must not fabricate an open
    print even when prior-day data is present and the gap shape is obvious."""
    # Day 1: some bars ending at prior close 100
    i1 = pd.date_range("2026-06-08 15:30", periods=30, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    d1 = pd.DataFrame({"open": 100.0, "high": 100.05, "low": 99.95,
                        "close": 100.0, "volume": 5_000.0}, index=i1)
    # Day 2: starts at 10:01 ET (09:30 bar is absent from the window)
    i2 = pd.date_range("2026-06-09 10:01", periods=10, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series([103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7, 103.8, 104.0],
                  index=i2)
    d2 = pd.DataFrame({"open": c, "high": c + 0.05, "low": c - 0.05,
                        "close": c, "volume": 20_000.0})
    df = pd.concat([d1, d2])
    assert generate(df, gap_min_pct=2.0, confirm_minutes=5)["buy"] is False
