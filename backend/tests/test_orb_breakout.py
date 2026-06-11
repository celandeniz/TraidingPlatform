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
