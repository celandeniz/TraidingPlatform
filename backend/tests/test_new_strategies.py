import pandas as pd

from backend.strategy.donchian_breakout import generate as donchian
from backend.strategy.ema_momentum import generate as ema_mom
from backend.strategy.registry import (
    build_confirmation_strategies, build_signal_strategies,
)
from backend.strategy.volume_confirm import score_volume


def _ohlc(closes, highs=None, lows=None, vols=None):
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs if highs is not None else [c + 1 for c in closes],
        "low": lows if lows is not None else [c - 1 for c in closes],
        "close": closes,
        "volume": vols if vols is not None else [100] * n,
    })


# ---- EMA momentum ---------------------------------------------------------
def test_ema_momentum_buy_on_cross_up():
    # flat (spread 0) then one tick up -> fast EMA crosses above slow on last bar
    res = ema_mom(_ohlc([100.0] * 30 + [101.0]), fast=12, slow=26)
    assert res["buy"] is True and res["sell"] is False


def test_ema_momentum_sell_on_cross_down():
    res = ema_mom(_ohlc([100.0] * 30 + [99.0]), fast=12, slow=26)
    assert res["sell"] is True and res["buy"] is False


def test_ema_momentum_flat_no_signal():
    res = ema_mom(_ohlc([100.0] * 40), fast=12, slow=26)
    assert not res["buy"] and not res["sell"]


# ---- Donchian breakout ----------------------------------------------------
def test_donchian_buy_on_new_high():
    df = _ohlc([100.0] * 25 + [105.0], highs=[100.5] * 25 + [105.5])
    res = donchian(df, channel=20)
    assert res["buy"] is True


def test_donchian_sell_on_new_low():
    df = _ohlc([100.0] * 25 + [95.0], lows=[99.5] * 25 + [94.5])
    res = donchian(df, channel=20)
    assert res["sell"] is True


def test_donchian_no_breakout_in_range():
    res = donchian(_ohlc([100.0] * 26), channel=20)
    assert not res["buy"] and not res["sell"]


# ---- Volume confirmation --------------------------------------------------
def test_volume_passes_on_spike():
    res = score_volume(_ohlc([100.0] * 21, vols=[100] * 20 + [200]), window=20, mult=1.5)
    assert res["passed"] is True and res["ratio"] > 1.5


def test_volume_fails_on_quiet():
    res = score_volume(_ohlc([100.0] * 21, vols=[100] * 21), window=20, mult=1.5)
    assert res["passed"] is False


# ---- Registry wiring ------------------------------------------------------
def test_registry_builds_all_active_strategies():
    cfg = {"strategies": {
        "signal": ["spike_fade", "ema_momentum", "donchian_breakout"],
        "confirmations": ["bollinger", "volume"],
    }}
    sigs = build_signal_strategies(cfg)
    confs = build_confirmation_strategies(cfg)
    assert [s.name for s in sigs] == ["spike_fade", "ema_momentum", "donchian_breakout"]
    assert [c.name for c in confs] == ["bollinger", "volume"]
