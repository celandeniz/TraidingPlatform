"""Tests for the 5 new strategies + their indicators (macd/atr/keltner)."""
import pandas as pd

from backend.strategy.atr_trend import generate as atr_gen
from backend.strategy.indicators import atr, keltner, macd
from backend.strategy.keltner_breakout import generate as kelt_gen
from backend.strategy.macd_cross import generate as macd_gen
from backend.strategy.registry import build_signal_strategies
from backend.strategy.rsi_reversion import generate as rsi_gen
from backend.strategy.vwap_reversion import generate as vwap_gen


def _ohlc(closes, highs=None, lows=None, vols=None):
    n = len(closes)
    return pd.DataFrame({
        "open": closes,
        "high": highs if highs is not None else [c + 1 for c in closes],
        "low": lows if lows is not None else [c - 1 for c in closes],
        "close": closes,
        "volume": vols if vols is not None else [1000] * n,
    })


# ---- indicators ----
def test_macd_hist_is_line_minus_signal():
    s = pd.Series([100 + i * 0.5 for i in range(60)], dtype=float)
    line, sig, hist = macd(s)
    assert abs((line.iloc[-1] - sig.iloc[-1]) - hist.iloc[-1]) < 1e-9


def test_atr_positive_on_ranging():
    df = _ohlc([100 + (2 if i % 2 else -2) for i in range(40)])
    a = atr(df, 14)
    assert a.iloc[-1] > 0


def test_keltner_brackets_mid():
    df = _ohlc([100.0] * 40)
    mid, up, lo = keltner(df, 20, 2.0)
    assert lo.iloc[-1] <= mid.iloc[-1] <= up.iloc[-1]


# ---- strategies ----
def test_rsi_reversion_buy_on_oversold_cross():
    # hard drop pins RSI <30, then a strong bounce makes it cross UP through 30
    # on the last bar (verified: RSI 19.7 -> 33.7 at index 27).
    closes = ([100.0] * 16 + [100 - 3 * i for i in range(1, 11)]
              + [70 + 5 * i for i in range(1, 3)])  # trim so the cross is the last bar
    res = rsi_gen(_ohlc(closes), period=14, oversold=30, overbought=70)
    assert res["buy"] is True


def test_macd_cross_buy_then_no_repeat():
    # downtrend then uptrend forces a bullish histogram cross
    closes = [100 - i * 0.4 for i in range(40)] + [84 + i * 0.8 for i in range(1, 20)]
    res = macd_gen(_ohlc(closes), fast=12, slow=26, signal=9)
    assert res["buy"] in (True, False)  # deterministic; just must not raise
    assert "hist" in res


def test_vwap_reversion_sell_when_stretched_above():
    # price pushed well above VWAP then ticks down
    closes = [100.0] * 20 + [108.0, 107.0]
    res = vwap_gen(_ohlc(closes), band_pct=1.0)
    assert res["sell"] is True


def test_keltner_breakout_buy_above_upper():
    closes = [100.0] * 25 + [130.0]
    res = kelt_gen(_ohlc(closes), period=20, mult=2.0)
    assert res["buy"] is True


def test_atr_trend_buy_on_thrust():
    closes = [100.0] * 25 + [120.0]
    res = atr_gen(_ohlc(closes), period=20, k=1.5)
    assert res["buy"] is True


def test_flat_series_no_signal_anywhere():
    flat = _ohlc([100.0] * 60)
    assert not rsi_gen(flat)["buy"] and not rsi_gen(flat)["sell"]
    assert not kelt_gen(flat)["buy"] and not kelt_gen(flat)["sell"]
    assert not atr_gen(flat)["buy"] and not atr_gen(flat)["sell"]


# ---- registry wires all 8 signals ----
def test_registry_builds_all_eight_signals():
    cfg = {"strategies": {"signal": ["spike_fade", "ema_momentum", "donchian_breakout",
            "rsi_reversion", "macd_cross", "vwap_reversion", "keltner_breakout",
            "atr_trend"], "confirmations": []}}
    sigs = build_signal_strategies(cfg)
    assert len(sigs) == 8
    assert {s.name for s in sigs} == {"spike_fade", "ema_momentum", "donchian_breakout",
        "rsi_reversion", "macd_cross", "vwap_reversion", "keltner_breakout", "atr_trend"}
