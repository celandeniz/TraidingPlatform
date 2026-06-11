"""Pairs: cointegration selection + spread z-score backtest on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.backtest.pairs_engine import find_pairs, run_pairs_backtest


def _coint_pair(n: int = 600, seed: int = 7):
    rng = np.random.default_rng(seed)
    a = 100 + np.cumsum(rng.normal(0, 0.5, n))
    spread = np.zeros(n)
    for i in range(1, n):                       # strongly mean-reverting spread
        spread[i] = 0.8 * spread[i - 1] + rng.normal(0, 0.4)
    b = a + spread
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    f = lambda px: pd.DataFrame({"open": px, "high": px, "low": px,
                                 "close": px, "volume": 1e6}, index=idx)
    return f(a), f(b)


def _random_pair(n: int = 600, seed: int = 11):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n, tz="UTC")
    f = lambda px: pd.DataFrame({"open": px, "high": px, "low": px,
                                 "close": px, "volume": 1e6}, index=idx)
    return (f(100 + np.cumsum(rng.normal(0, 0.5, n))),
            f(100 + np.cumsum(rng.normal(0, 0.5, n))))


def test_find_pairs_detects_cointegration_and_rejects_random():
    ca, cb = _coint_pair()
    ra, rb = _random_pair()
    frames = {"KO": ca, "PEP": cb, "RND1": ra, "RND2": rb}
    pairs = find_pairs(frames, corr_min=0.5, pval_max=0.05, top_n=5)
    keys = {(p.sym_a, p.sym_b) for p in pairs}
    assert ("KO", "PEP") in keys or ("PEP", "KO") in keys
    assert all({"RND1", "RND2"} != {p.sym_a, p.sym_b} for p in pairs)


def test_pairs_backtest_trades_and_profits_on_mean_reverting_spread():
    ca, cb = _coint_pair()
    res = run_pairs_backtest(ca, cb, z_entry=2.0, z_exit=0.0, z_stop=3.5,
                             max_days=30, hedge_window=60, cost_bps=0.0)
    assert res["n_trades"] >= 5
    assert res["total_return_pct"] > 0          # mean reversion is real here
    assert all("ret_pct" in t for t in res["trades"])


def test_pairs_backtest_costs_reduce_return():
    ca, cb = _coint_pair()
    free = run_pairs_backtest(ca, cb, cost_bps=0.0)
    costly = run_pairs_backtest(ca, cb, cost_bps=20.0)
    assert costly["total_return_pct"] < free["total_return_pct"]


def test_run_pairs_strategy_selects_on_train_only():
    from backend.strategy.pairs_statarb import run_pairs_strategy
    ca, cb = _coint_pair(n=800, seed=7)
    ra, rb = _random_pair(n=800, seed=11)
    frames = {"KO": ca, "PEP": cb, "RND1": ra, "RND2": rb}
    res = run_pairs_strategy(frames, corr_min=0.5, cost_bps=0.0)
    assert res["error"] == ""
    assert "KO/PEP" in res["pairs"] or "PEP/KO" in res["pairs"]
    assert res["n_trades"] >= 1
    assert all(t["entry_idx"] >= 0 for t in res["trades"])


# ---------------------------------------------------------------------------
# Item 1: eod_close force-liquidation — open position at end of data is recorded
# ---------------------------------------------------------------------------

def test_eod_close_liquidation():
    """A position still open at last bar must be force-liquidated with reason 'eod_close'."""
    ca, cb = _coint_pair(n=600, seed=7)
    # Run once on the full pair to find an entry index
    full_res = run_pairs_backtest(ca, cb, z_entry=2.0, z_exit=0.0, z_stop=3.5,
                                  max_days=30, hedge_window=60, cost_bps=0.0)
    assert full_res["n_trades"] >= 1, "fixture must produce at least one trade"
    # Find the first trade's entry index in the aligned series
    first_trade = full_res["trades"][0]
    entry_idx = first_trade["entry_idx"]

    # Truncate both frames to entry_idx + 3 bars so the exit never triggers
    # (only 2 bars beyond entry, which is entry fill + 2 signal bars — far fewer
    # than z_exit / z_stop / max_days would need).
    cut = entry_idx + 3
    ca_short = ca.iloc[:cut].copy()
    cb_short = cb.iloc[:cut].copy()

    res = run_pairs_backtest(ca_short, cb_short, z_entry=2.0, z_exit=0.0,
                             z_stop=3.5, max_days=30, hedge_window=60,
                             cost_bps=0.0)
    assert res["n_trades"] >= 1, "truncated run must still record the eod_close trade"
    last_trade = res["trades"][-1]
    assert last_trade["reason"] == "eod_close", (
        f"expected 'eod_close', got {last_trade['reason']!r}"
    )


# ---------------------------------------------------------------------------
# Item 2: max_tests bounds coint candidate count
# ---------------------------------------------------------------------------

def test_find_pairs_max_tests_bounds_coint():
    """max_tests=1 must still return a result (best-corr candidate only) without error."""
    ca, cb = _coint_pair()
    ra, rb = _random_pair()
    frames = {"KO": ca, "PEP": cb, "RND1": ra, "RND2": rb}
    # With max_tests=1, only the most-correlated pair is tested for cointegration.
    # It should not raise and should return a list (possibly empty if that pair doesn't coint).
    pairs = find_pairs(frames, corr_min=0.5, pval_max=0.05, top_n=5, max_tests=1)
    assert isinstance(pairs, list)


def test_find_pairs_max_tests_default_unaffected():
    """Default max_tests (2000) leaves small universes (4 symbols) completely unaffected."""
    ca, cb = _coint_pair()
    ra, rb = _random_pair()
    frames = {"KO": ca, "PEP": cb, "RND1": ra, "RND2": rb}
    pairs_default = find_pairs(frames, corr_min=0.5, pval_max=0.05, top_n=5)
    pairs_large = find_pairs(frames, corr_min=0.5, pval_max=0.05, top_n=5, max_tests=2000)
    # Both should produce identical results
    assert len(pairs_default) == len(pairs_large)
    for p1, p2 in zip(pairs_default, pairs_large):
        assert p1.sym_a == p2.sym_a and p1.sym_b == p2.sym_b
