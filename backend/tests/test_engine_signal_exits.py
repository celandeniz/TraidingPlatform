"""Per-signal exit overrides: a signal dict may carry stop_loss_pct /
take_profit_pct / time_stop_bars that override ExitParams for that trade only."""
import pandas as pd

from backend.backtest.engine import CostModel, ExitParams, run_backtest


def _df(prices: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-05 14:30", periods=len(prices), freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": prices, "high": [p * 1.001 for p in prices],
         "low": [p * 0.999 for p in prices], "close": prices,
         "volume": [1000] * len(prices)},
        index=idx,
    )


def test_signal_stop_override_used_instead_of_exitparams():
    # Flat 100s, entry signal once warm, then a drop to 97 that would NOT hit the
    # wide default stop (10%) but MUST hit the per-signal 1% stop.
    # Signal fires at len(window)==40 (bar 39); entry fills at bar 40, which must
    # still be 100.0 so the 1% stop (~99.0) is meaningful before the 97 bars.
    prices = [100.0] * 41 + [97.0] * 5
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            return {"buy": True, "stop_loss_pct": 1.0, "take_profit_pct": 50.0}
        return {}

    res = run_backtest(df, sig, exits=ExitParams(take_profit_pct=50.0, stop_loss_pct=10.0),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].entry_px == 100.0  # guards fixture's entry-fill alignment
    assert res.trades[0].reason == "stop_loss"
    # stop at 1% below entry (~100), so exit ~99 — not the default 90
    assert res.trades[0].exit_px > 95.0


def test_signal_time_stop_override():
    prices = [100.0] * 60
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            return {"buy": True, "stop_loss_pct": 50.0, "take_profit_pct": 50.0,
                    "time_stop_bars": 3}
        return {}

    res = run_backtest(df, sig, exits=ExitParams(take_profit_pct=50.0, stop_loss_pct=50.0,
                                                 time_stop_bars=None),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].reason == "time_stop"
    assert res.trades[0].bars_held == 3


def test_no_override_keys_uses_global_exit_params():
    # Signal carries NO override keys — must fall back to global stop_loss_pct=1.0.
    # Price drops 3% after entry, which would NOT trigger global stop=50% but must
    # trigger the 1%-global stop that was passed via ExitParams.
    prices = [100.0] * 41 + [97.0] * 5
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            return {"buy": True}  # no override keys at all
        return {}

    res = run_backtest(df, sig,
                       exits=ExitParams(stop_loss_pct=1.0, take_profit_pct=50.0),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].reason == "stop_loss"
    assert res.trades[0].exit_px > 95.0  # stopped at ~99, not at 50%-down


def test_explicit_none_override_falls_back_to_global():
    # Signal explicitly passes None for stop_loss_pct — must NOT crash and must
    # fall back to the global stop (1%), triggering on the 3% price drop.
    prices = [100.0] * 41 + [97.0] * 5
    df = _df(prices)
    fired = {"done": False}

    def sig(window):
        if len(window) == 40 and not fired["done"]:
            fired["done"] = True
            # Explicit None — old code would store None and crash in stop calc
            return {"buy": True, "stop_loss_pct": None, "take_profit_pct": None,
                    "time_stop_bars": None}
        return {}

    res = run_backtest(df, sig,
                       exits=ExitParams(stop_loss_pct=1.0, take_profit_pct=50.0),
                       costs=CostModel(0.0, 0.0), warmup=30)
    assert res.n_trades == 1
    assert res.trades[0].reason == "stop_loss"
    assert res.trades[0].exit_px > 95.0  # stopped at ~99 via global 1% stop
