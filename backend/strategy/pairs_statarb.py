"""Pairs stat-arb orchestrator for the tournament.

Honest split: pairs are SELECTED on the first train_frac of history only, then
TRADED on the remaining test slice — selection never sees test data. Aggregates
trades across the chosen pairs.
"""
from __future__ import annotations

import pandas as pd

from backend.backtest.pairs_engine import find_pairs, run_pairs_backtest


def run_pairs_strategy(frames: dict, *, train_frac: float = 0.6,
                       corr_min: float = 0.8, pval_max: float = 0.05,
                       top_n: int = 10, max_tests: int = 2000,
                       z_entry: float = 2.0, z_exit: float = 0.0,
                       z_stop: float = 3.5, max_days: int = 30,
                       hedge_window: int = 60, cost_bps: float = 3.0) -> dict:
    if not frames:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": "no data"}
    n = min(len(f) for f in frames.values())
    cut = int(n * train_frac)
    if cut < hedge_window + 30 or n - cut < hedge_window + 10:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": "insufficient data"}

    train = {s: f.iloc[:cut] for s, f in frames.items()}
    pairs = find_pairs(train, corr_min=corr_min, pval_max=pval_max, top_n=top_n,
                       max_tests=max_tests)
    if not pairs:
        return {"n_trades": 0, "trades": [], "pairs": [], "error": ""}

    all_trades, total_ret = [], 0.0
    for p in pairs:
        test_a = frames[p.sym_a].iloc[cut - hedge_window:]   # warm hedge window
        test_b = frames[p.sym_b].iloc[cut - hedge_window:]
        res = run_pairs_backtest(test_a, test_b, z_entry=z_entry, z_exit=z_exit,
                                 z_stop=z_stop, max_days=max_days,
                                 hedge_window=hedge_window, cost_bps=cost_bps)
        for t in res["trades"]:
            t["pair"] = f"{p.sym_a}/{p.sym_b}"
        all_trades.extend(res["trades"])
        total_ret += res["total_return_pct"] / len(pairs)   # equal capital per pair
    return {"n_trades": len(all_trades), "trades": all_trades,
            "total_return_pct": total_ret,
            "pairs": [f"{p.sym_a}/{p.sym_b}" for p in pairs], "error": ""}
