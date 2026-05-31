"""Symbol selector tests — whitelist logic + validation plumbing (synthetic data)."""
import numpy as np
import pandas as pd

from backend.backtest.selector import select_symbols, validate_selection


def _series(n, kind, seed):
    rng = np.random.default_rng(seed)
    if kind == "trend":
        base = 100 + np.arange(n) * 0.03
    else:  # choppy mean-reverting
        base = 100 + 4 * np.sin(np.arange(n) / 8.0)
    noise = rng.standard_normal(n) * 0.4
    close = base + noise
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": close, "high": close + 0.5, "low": close - 0.5,
                         "close": close, "volume": [1000] * n}, index=idx)


def test_select_returns_verdict_per_symbol():
    data = {"AAA": _series(600, "trend", 1), "BBB": _series(600, "chop", 2)}
    sel = select_symbols(data, n_folds=3)
    syms = {v.symbol for v in sel.verdicts}
    assert syms == {"AAA", "BBB"}
    # tradable + excluded partition all symbols
    assert set(sel.tradable) | set(sel.excluded) == {"AAA", "BBB"}
    assert not (set(sel.tradable) & set(sel.excluded))


def test_threshold_excludes_negative_oos():
    # a single symbol; with an impossibly high bar nothing should be tradable
    data = {"AAA": _series(600, "chop", 3)}
    sel = select_symbols(data, n_folds=3, min_oos_return=999.0)
    assert sel.tradable == []
    assert sel.excluded == ["AAA"]


def test_validate_selection_runs_split():
    data = {"AAA": _series(800, "trend", 4), "BBB": _series(800, "chop", 5),
            "CCC": _series(800, "trend", 6)}
    out = validate_selection(data, n_folds=3)
    # keys present and partition is from the EARLY half
    assert "early_tradable" in out and "late_oos_of_chosen" in out
    assert "verdict" in out
    assert set(out["early_tradable"]) | set(out["early_excluded"]) == {"AAA", "BBB", "CCC"}


def test_portfolio_oos_fields_present():
    data = {"AAA": _series(600, "trend", 7), "BBB": _series(600, "chop", 8)}
    sel = select_symbols(data, n_folds=3)
    assert isinstance(sel.all_avg_oos, float)
    assert isinstance(sel.tradable_avg_oos, float)
