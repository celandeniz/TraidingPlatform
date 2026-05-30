import numpy as np
import pandas as pd

from backend.strategy.indicators import bollinger, ema, rsi, vwap, zscore


def test_rsi_all_gains_is_100():
    close = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16], dtype=float)
    r = rsi(close, 14)
    assert r.iloc[-1] == 100.0


def test_rsi_in_bounds():
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.standard_normal(200).cumsum())
    r = rsi(close, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_zscore_constant_series_is_nan_or_zero():
    s = pd.Series([5.0] * 30)
    z = zscore(s, 20)
    # std is 0 -> division yields NaN; that's acceptable (no dispersion).
    assert pd.isna(z.iloc[-1]) or z.iloc[-1] == 0


def test_ema_tracks_constant():
    s = pd.Series([10.0] * 50)
    assert abs(ema(s, 10).iloc[-1] - 10.0) < 1e-9


def test_vwap_matches_manual():
    df = pd.DataFrame(
        {"high": [10, 12], "low": [8, 10], "close": [9, 11], "volume": [100, 300]}
    )
    # typical: 9 and 11; cum pv = 900, 900+3300=4200; cum vol = 100, 400
    v = vwap(df)
    assert abs(v.iloc[0] - 9.0) < 1e-9
    assert abs(v.iloc[1] - (4200 / 400)) < 1e-9


def test_bollinger_constant_series_zero_width():
    s = pd.Series([20.0] * 25)
    mid, upper, lower = bollinger(s, 20, 2.0)
    assert abs(mid.iloc[-1] - 20.0) < 1e-9
    assert abs(upper.iloc[-1] - 20.0) < 1e-9
    assert abs(lower.iloc[-1] - 20.0) < 1e-9


def test_bollinger_width_matches_std():
    s = pd.Series(list(range(1, 21)), dtype=float)  # 1..20
    mid, upper, lower = bollinger(s, 20, 2.0)
    dev = s.std(ddof=0)
    assert abs((upper.iloc[-1] - mid.iloc[-1]) - 2.0 * dev) < 1e-9
    assert abs((mid.iloc[-1] - lower.iloc[-1]) - 2.0 * dev) < 1e-9
