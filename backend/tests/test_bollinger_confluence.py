import pandas as pd

from backend.strategy.bollinger_confluence import score_confluence

TFS = ["1m", "3m", "5m", "15m", "45m", "1h"]


def _below_lower_df():
    # 20 flat bars then a hard drop on the last bar -> close < lower band.
    return pd.DataFrame({"close": pd.Series([100.0] * 20 + [80.0])})


def _above_upper_df():
    return pd.DataFrame({"close": pd.Series([100.0] * 20 + [120.0])})


def _in_band_df():
    return pd.DataFrame({"close": pd.Series([100.0] * 21)})


def test_all_timeframes_agree_buy_scores_six_confirmed():
    per_tf = {tf: _below_lower_df() for tf in TFS}
    res = score_confluence("buy", per_tf, period=20, std=2.0, confirm_min=3)
    assert res["bb_score"] == 6
    assert res["bb_confirmed"] is True


def test_none_agree_scores_zero_unconfirmed():
    per_tf = {tf: _in_band_df() for tf in TFS}
    res = score_confluence("buy", per_tf, period=20, std=2.0, confirm_min=3)
    assert res["bb_score"] == 0
    assert res["bb_confirmed"] is False


def test_threshold_boundary_is_confirmed():
    # Exactly 3 agree, 3 in-band.
    per_tf = {tf: _below_lower_df() for tf in TFS[:3]}
    per_tf.update({tf: _in_band_df() for tf in TFS[3:]})
    res = score_confluence("buy", per_tf, period=20, std=2.0, confirm_min=3)
    assert res["bb_score"] == 3
    assert res["bb_confirmed"] is True


def test_sell_uses_upper_band():
    per_tf = {tf: _above_upper_df() for tf in TFS}
    res = score_confluence("sell", per_tf, period=20, std=2.0, confirm_min=3)
    assert res["bb_score"] == 6
    assert res["bb_confirmed"] is True
    # A buy signal on the same data should NOT agree.
    res_buy = score_confluence("buy", per_tf, period=20, std=2.0, confirm_min=3)
    assert res_buy["bb_score"] == 0
