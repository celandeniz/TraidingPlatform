import pandas as pd

from backend.strategy.regime import detect


def test_rising_series_is_up():
    df = pd.DataFrame({"close": pd.Series(range(1, 80), dtype=float)})
    assert detect(df, ema_period=50, slope_threshold=0.0005) == "up"


def test_falling_series_is_down():
    df = pd.DataFrame({"close": pd.Series(range(80, 1, -1), dtype=float)})
    assert detect(df, ema_period=50, slope_threshold=0.0005) == "down"


def test_flat_series_is_range():
    df = pd.DataFrame({"close": pd.Series([100.0] * 80)})
    assert detect(df, ema_period=50, slope_threshold=0.0005) == "range"
