"""run_one backtest helper — strategy map + daily/intraday routing, no network."""
import numpy as np
import pandas as pd
import pytest

from backend.backtest.run_one import (
    DAILY_TIMEFRAMES, available_strategies, run_one,
)


def _df(n=400):
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    t = np.arange(n)
    close = 100 + 10 * np.sin(t / 8.0) + np.sin(t / 3.0)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + 0.5,
         "low": np.minimum(open_, close) - 0.5, "close": close,
         "volume": np.full(n, 1_000_000.0)}, index=idx)


def test_available_strategies_lists_generic_signals():
    keys = available_strategies()
    assert "rsi_reversion" in keys and "ema_momentum" in keys
    assert "orb_breakout" not in keys and "gap_go" not in keys


def test_run_one_produces_metrics():
    res = run_one(_df(), "rsi_reversion", take_profit_pct=2.0, stop_loss_pct=1.5)
    assert res.error == "" and res.n_trades > 0


def test_run_one_unknown_strategy_raises():
    with pytest.raises(KeyError):
        run_one(_df(), "does_not_exist")


def test_daily_timeframes_set():
    assert "1d" in DAILY_TIMEFRAMES and "5m" not in DAILY_TIMEFRAMES
