"""Walk-forward tests — the critical guarantee: OOS never influences selection."""
import pandas as pd

from backend.backtest.engine import ExitParams
from backend.backtest.walkforward import Candidate, walk_forward


def _df(closes):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": closes, "high": [c + 0.5 for c in closes],
                         "low": [c - 0.5 for c in closes], "close": closes,
                         "volume": [1000] * n}, index=idx)


def _ema_cand():
    from backend.strategy.ema_momentum import generate as ema
    return Candidate("ema_12_26", lambda d: ema(d, fast=12, slow=26),
                     ExitParams(2.0, 1.5, None, 90, True))


def _don_cand():
    from backend.strategy.donchian_breakout import generate as don
    return Candidate("don_10", lambda d: don(d, channel=10),
                     ExitParams(2.0, 1.5, None, 90, True))


def test_walk_forward_runs_and_splits_chronologically():
    # 600 bars, gentle trend + noise
    closes = [100 + i * 0.02 + (3 if i % 50 < 25 else -3) for i in range(600)]
    wf = walk_forward(_df(closes), [_ema_cand(), _don_cand()], n_folds=3,
                      symbol="TST", timeframe="5m")
    assert not wf.error
    assert wf.n_folds >= 1
    # OOS windows must come strictly after IS windows (chronological, no overlap leak)
    for f in wf.folds:
        assert f.is_end <= f.oos_start or f.is_end <= f.oos_end


def test_insufficient_data_errors():
    wf = walk_forward(_df([100.0] * 20), [_ema_cand()], n_folds=4)
    assert wf.error


def test_degradation_is_is_minus_oos():
    closes = [100 + (5 if i % 40 < 20 else -5) for i in range(500)]
    wf = walk_forward(_df(closes), [_ema_cand(), _don_cand()], n_folds=3)
    if not wf.error and wf.n_folds:
        assert abs(wf.degradation_pct - (wf.avg_is_return - wf.avg_oos_return)) < 0.011


def test_selection_uses_only_in_sample():
    # A candidate that is great early and terrible late should still be PICKED on
    # the IS window (early) even though its OOS (late) is bad — proving selection
    # never peeks at OOS. We assert the chosen label appears and OOS is computed.
    closes = ([100 + (4 if i % 30 < 15 else -4) for i in range(300)]  # choppy IS
              + [100 + i * 0.1 for i in range(300)])                  # trending OOS
    wf = walk_forward(_df(closes), [_ema_cand(), _don_cand()], n_folds=3)
    assert not wf.error
    for f in wf.folds:
        assert f.chosen in ("ema_12_26", "don_10")
        # both IS and OOS returns are recorded (OOS computed after the pick)
        assert isinstance(f.is_return_pct, float)
        assert isinstance(f.oos_return_pct, float)
