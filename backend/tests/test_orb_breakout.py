"""ORB: break of the 09:30-09:45 ET opening range, with range-based exits."""
import pandas as pd

from backend.strategy.orb_breakout import generate


def _session(closes_by_minute: list[float], day: str = "2026-06-08") -> pd.DataFrame:
    """1m bars starting 09:30 ET. closes drive OHLC (tight bars)."""
    idx = pd.date_range(f"{day} 09:30", periods=len(closes_by_minute),
                        freq="1min", tz="America/New_York").tz_convert("UTC")
    c = pd.Series(closes_by_minute, index=idx)
    return pd.DataFrame({"open": c.shift(1).fillna(c.iloc[0]), "high": c + 0.05,
                         "low": c - 0.05, "close": c, "volume": 10_000.0})


def _bars(
    start_time: str,
    closes: list[float],
    day: str,
    volume: float = 10_000.0,
) -> pd.DataFrame:
    """Generic 1m bars from any start_time. start_time e.g. '10:01'."""
    idx = pd.date_range(
        f"{day} {start_time}",
        periods=len(closes),
        freq="1min",
        tz="America/New_York",
    ).tz_convert("UTC")
    c = pd.Series(closes, index=idx)
    return pd.DataFrame(
        {
            "open": c.shift(1).fillna(c.iloc[0]),
            "high": c + 0.05,
            "low": c - 0.05,
            "close": c,
            "volume": volume,
        }
    )


def _concat(*frames: pd.DataFrame) -> pd.DataFrame:
    """Concatenate bar frames and sort by time."""
    return pd.concat(list(frames)).sort_index()


def test_breakout_above_range_fires_buy_with_range_exits():
    # 15 min flat 100.0..100.4 (range hi ~100.45 incl wick), then a bar closing 101.0
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [101.0]
    df = _session(closes)
    sig = generate(df, range_minutes=15, min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is True and sig["sell"] is False
    assert sig["stop_loss_pct"] > 0          # stop = far side of the range
    assert sig["take_profit_pct"] >= 2 * sig["stop_loss_pct"] * 0.99  # ~2R
    assert sig["time_stop_bars"] > 0          # bars until 15:55 ET


def test_inside_range_no_signal():
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [100.2]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False and sig["sell"] is False


def test_during_range_formation_no_signal():
    closes = [100.0, 100.1, 105.0]            # only 3 minutes in — range not formed
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False and sig["sell"] is False


def test_breakdown_below_range_fires_sell():
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [99.0]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["sell"] is True and sig["buy"] is False


def test_only_first_breakout_bar_fires():
    # bar 16 breaks out; bar 17 is still above the range but must NOT re-fire
    closes = [100.0 + (i % 5) * 0.1 for i in range(15)] + [101.0, 101.2]
    sig = generate(_session(closes), range_minutes=15,
                   min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False


# ---------------------------------------------------------------------------
# NEW TESTS — written first (TDD) against the unfixed code; they will fail
# until the 09:30-anchor fix and filter fixes are applied.
# ---------------------------------------------------------------------------

def test_window_missing_session_open_no_signal():
    """Rolling window starts at 10:01 (past the open) — must return no signal.

    The session data starts at 10:01 so the 09:30 anchor is missing.  An
    obvious breakout shape is present so the only reason to return no-signal
    is the anchor check.
    """
    day = "2026-06-09"
    # 15 flat bars 10:01..10:15, then a bar well above "range" at 10:16
    # If the code takes the first N rows as the range it would see a breakout.
    # Correct code must reject because index[0].time() != 09:30.
    flat = [100.0] * 15
    closes = flat + [102.0]
    df = _bars("10:01", closes, day)
    sig = generate(df, range_minutes=15, min_rel_volume=0.0, min_range_atr=0.0)
    assert sig["buy"] is False and sig["sell"] is False, (
        "Window missing 09:30 open bar must return no signal"
    )


def test_rel_volume_filter_rejects_low_volume_breakout():
    """Relative-volume filter: low today-volume → no signal; high → signal fires.

    Build 3 prior full-ish sessions (30 1m bars each, volume=50_000/bar) so
    avg cumulative volume is high.  Today's session has volume=1_000/bar
    (well below 1.5× avg) → no signal.  Then raise today-volume to 200_000/bar
    → signal must fire — proving the filter is the discriminator.
    """
    # Prior sessions: 3 days, 30 bars each starting at 09:30, vol=50_000
    prior_days = ["2026-06-03", "2026-06-04", "2026-06-05"]
    # Flat closes so they don't accidentally produce a range-hi near today's close.
    prior_closes = [100.0] * 30
    prior_frames = [
        _bars("09:30", prior_closes, d, volume=50_000.0) for d in prior_days
    ]

    today = "2026-06-08"
    # 15 flat range bars then a breakout bar
    today_closes = [100.0] * 15 + [102.0]

    # --- low volume: expect no signal ---
    today_low_vol = _bars("09:30", today_closes, today, volume=1_000.0)
    df_low = _concat(*prior_frames, today_low_vol)
    sig_low = generate(
        df_low, range_minutes=15, min_rel_volume=1.5, min_range_atr=0.0
    )
    assert sig_low["buy"] is False and sig_low["sell"] is False, (
        "Low relative volume must suppress the signal"
    )

    # --- high volume: expect buy signal ---
    today_high_vol = _bars("09:30", today_closes, today, volume=200_000.0)
    df_high = _concat(*prior_frames, today_high_vol)
    sig_high = generate(
        df_high, range_minutes=15, min_rel_volume=1.5, min_range_atr=0.0
    )
    assert sig_high["buy"] is True, (
        "High relative volume must allow the signal to fire"
    )


def test_atr_filter_rejects_narrow_range():
    """ATR filter: narrow opening range → no signal.

    Build 15 prior sessions with wide daily ranges (closes alternating ±2.0
    each bar so daily ATR is large).  Today's session has a tiny opening range
    (±0.05 tight bars) so range_hi - range_lo ≈ 0.10, which is < 0.3 × ATR.
    With min_range_atr=0.3 the signal must be suppressed.

    Math check:
      Each prior session has 30 1m bars.  high = close+0.05, low = close-0.05.
      But daily high = max(close)+0.05, daily low = min(close)-0.05.
      With closes [100, 102, 100, 102, ...] → daily high≈102.05, low≈99.95
      → daily range ≈ 2.10.  TR ≈ 2.10 per day → ATR(14) ≈ 2.10.
      Today opening range = max(close) - min(close) + 0.10 (wicks)
        = 0.0 + 0.10 = 0.10.
      0.10 < 0.3 × 2.10 = 0.63 → filter rejects. ✓
    """
    prior_days = [
        f"2026-05-{d:02d}" for d in range(5, 26)  # 21 trading days
    ]
    # Alternating closes produce wide daily range
    wide_closes = [100.0 + 2.0 * (i % 2) for i in range(30)]  # 100 or 102
    prior_frames = [
        _bars("09:30", wide_closes, d, volume=50_000.0) for d in prior_days
    ]

    today = "2026-06-08"
    # Flat 100.0 for 15 bars (tiny range) then a marginal "breakout" bar.
    # range_hi = 100.0 + 0.05 = 100.05; close of bar 16 must be > range_hi.
    tiny_range_closes = [100.0] * 15 + [100.10]
    today_session = _bars("09:30", tiny_range_closes, today, volume=50_000.0)

    df = _concat(*prior_frames, today_session)
    sig = generate(df, range_minutes=15, min_rel_volume=0.0, min_range_atr=0.3)
    assert sig["buy"] is False and sig["sell"] is False, (
        "Narrow opening range must be rejected by the ATR filter"
    )
