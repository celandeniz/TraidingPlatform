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


def _two_days_with_postmarket(
    day1_rth_close: float,
    day1_pm_closes: list[float],
    day2_closes: list[float],
) -> pd.DataFrame:
    """Day 1: 30 RTH bars ending at day1_rth_close, then post-market bars
    drifting to the last value in day1_pm_closes. Day 2: 09:30 ET +."""
    # Day 1 RTH: 30 bars 15:30 ET onwards
    i1_rth = pd.date_range("2026-06-08 15:30", periods=30, freq="1min",
                           tz="America/New_York").tz_convert("UTC")
    d1_rth = pd.DataFrame({"open": day1_rth_close, "high": day1_rth_close + 0.05,
                           "low": day1_rth_close - 0.05, "close": day1_rth_close,
                           "volume": 5_000.0}, index=i1_rth)
    # Day 1 post-market: starts at 16:30 ET, drifts down
    i1_pm = pd.date_range("2026-06-08 16:30", periods=len(day1_pm_closes), freq="1min",
                          tz="America/New_York").tz_convert("UTC")
    pm_s = pd.Series(day1_pm_closes, index=i1_pm)
    d1_pm = pd.DataFrame({"open": pm_s.shift(1).fillna(pm_s.iloc[0]),
                          "high": pm_s + 0.05, "low": pm_s - 0.05,
                          "close": pm_s, "volume": 500.0})
    # Day 2 RTH
    i2 = pd.date_range("2026-06-09 09:30", periods=len(day2_closes), freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    c = pd.Series(day2_closes, index=i2)
    d2 = pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.05,
                       "low": c - 0.05, "close": c, "volume": 20_000.0})
    return pd.concat([d1_rth, d1_pm, d2])


def test_prev_close_uses_rth_close_not_postmarket():
    """Bug regression: prev_close must be the last RTH bar, not a post-market print.

    Day 1 RTH close = 100.0; post-market drifts to 98.0.
    Day 2 opens at 102.0: 2% above RTH close (100), but 4.08% above post-market (98).
    With gap_min_pct=3.0 the buy must NOT fire (gap vs RTH close is only 2%).
    Under the buggy code it would fire (measuring vs 98.0 → 4.08% gap).
    We also confirm the setup is otherwise valid: gap_min_pct=1.5 must fire.
    """
    # Day 2: open at 102.0, stays well above VWAP, bar 6 breaks the first-5-min high
    # Bars: [102.0, 101.9, 102.0, 102.1, 102.2, 102.6]
    # 5-min high = 102.2; bar 6 close = 102.6 > 102.2 -> breakout condition met
    day2 = [102.0, 101.9, 102.0, 102.1, 102.2, 102.6]
    # Post-market bars drift from 100 -> 98
    postmarket = [99.5, 99.0, 98.5, 98.2, 98.0]
    df = _two_days_with_postmarket(100.0, postmarket, day2)

    # gap vs RTH close = (102/100 - 1)*100 = 2.0% < 3.0% -> must NOT fire
    sig_high_threshold = generate(df, gap_min_pct=3.0, confirm_minutes=5)
    assert sig_high_threshold["buy"] is False, (
        "buy fired with gap_min_pct=3.0 — prev_close is being measured against "
        "a post-market bar instead of the RTH close"
    )

    # gap vs RTH close = 2.0% > 1.5% -> must fire (proves setup is otherwise valid)
    sig_low_threshold = generate(df, gap_min_pct=1.5, confirm_minutes=5)
    assert sig_low_threshold["buy"] is True, (
        "buy did not fire with gap_min_pct=1.5 — the day-2 fixture may not satisfy "
        "all other conditions (above VWAP, break of 5-min high, gap not filled)"
    )


def test_gap_down_short_fires_when_allowed():
    """Short path: prev RTH close 100, day 2 opens 97 (3% gap-down), stays below
    VWAP, breaks first-5-min low on bar 6, never trades back through 100."""
    # Day 2 closes: [97.0, 97.1, 97.0, 96.9, 96.8, 96.4]
    # 5-min low = 96.8; bar 6 close = 96.4 < 96.8 -> short breakout condition met
    day2 = [97.0, 97.1, 97.0, 96.9, 96.8, 96.4]
    df = _two_days(100.0, day2)

    sig_allowed = generate(df, gap_min_pct=2.0, confirm_minutes=5, allow_short=True)
    assert sig_allowed["sell"] is True, "sell did not fire with allow_short=True"

    sig_blocked = generate(df, gap_min_pct=2.0, confirm_minutes=5, allow_short=False)
    assert sig_blocked["sell"] is False, "sell fired with allow_short=False"


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
