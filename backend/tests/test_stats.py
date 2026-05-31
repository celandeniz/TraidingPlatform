"""Statistical-significance tests — protect against noise-as-edge."""
from backend.backtest.stats import bootstrap_ci, significance, t_statistic


def test_small_sample_not_significant():
    # 5 nicely-positive trades is still too few to be meaningful
    s = significance([1.0, 0.8, 1.2, 0.9, 1.1])
    assert s.n == 5
    assert s.significant is False
    assert "too few" in s.label


def test_large_consistent_positive_is_significant():
    # 40 tightly-clustered positive returns -> low p, CI excludes 0
    rets = [1.0 + (0.05 if i % 2 else -0.05) for i in range(40)]
    s = significance(rets)
    assert s.n == 40
    assert s.p_value < 0.05
    assert s.ci_low_pct > 0
    assert s.significant is True
    assert "significant positive" in s.label


def test_noisy_mean_zero_not_significant():
    # alternating +2/-2 around zero, large n -> not distinguishable from 0
    rets = [2.0 if i % 2 else -2.0 for i in range(40)]
    s = significance(rets)
    assert s.significant is False
    assert "noise" in s.label or "not significant" in s.label


def test_t_statistic_zero_for_symmetric():
    t, p = t_statistic([1.0, -1.0, 1.0, -1.0])
    assert abs(t) < 1e-9
    assert p > 0.9


def test_bootstrap_ci_brackets_mean():
    rets = [1.0] * 30
    lo, hi = bootstrap_ci(rets)
    assert abs(lo - 1.0) < 1e-6 and abs(hi - 1.0) < 1e-6  # zero variance -> tight CI


def test_significantly_negative_flagged():
    rets = [-1.0 + (0.05 if i % 2 else -0.05) for i in range(40)]
    s = significance(rets)
    assert s.significant is True
    assert "negative" in s.label
