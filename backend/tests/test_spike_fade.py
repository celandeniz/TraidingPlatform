import numpy as np
import pandas as pd

from backend.strategy.spike_fade import generate


def _df(prices):
    return pd.DataFrame({"close": pd.Series(prices, dtype=float)})


def test_drop_then_reversal_fires_buy():
    # Calm baseline, a sharp drop, then an up-tick on the last bar.
    prices = [100.0] * 25 + [99.0, 95.0, 90.0, 91.0]
    res = generate(_df(prices), zscore_window=20, lookback_k=3, z_entry=2.0)
    assert res["buy"] is True
    assert res["sell"] is False


def test_spike_then_reversal_fires_sell():
    prices = [100.0] * 25 + [101.0, 105.0, 110.0, 109.0]
    res = generate(_df(prices), zscore_window=20, lookback_k=3, z_entry=2.0)
    assert res["sell"] is True
    assert res["buy"] is False


def test_flat_series_fires_nothing():
    rng = np.random.default_rng(1)
    prices = 100 + rng.standard_normal(60) * 0.01  # tiny noise
    res = generate(_df(prices))
    assert res["buy"] is False
    assert res["sell"] is False
