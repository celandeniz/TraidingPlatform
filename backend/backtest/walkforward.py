"""Walk-forward (out-of-sample) validation — the honest test for overfitting.

In-sample (IS) optimization picks the best param set on a PAST window; the chosen
set is then run on the NEXT, unseen window (OOS). Repeat, rolling forward. A
strategy that only works in-sample (overfit) collapses out-of-sample. The IS->OOS
"degradation" is the headline number.

Anti-leakage guarantees:
  * Windows are split CHRONOLOGICALLY; OOS bars are strictly after IS bars.
  * Selection uses ONLY the IS slice; the OOS score is computed once, after the
    pick is frozen — the OOS data never influences which config is chosen.
  * The underlying backtest is itself no-lookahead (engine.py: next-bar-open fills).

Pure: give it a DataFrame + candidate configs, get a WalkForwardResult. No network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .engine import BacktestResult, CostModel, ExitParams, run_backtest


@dataclass
class Candidate:
    label: str
    signal_fn: Callable[[pd.DataFrame], dict]
    exits: ExitParams


@dataclass
class FoldResult:
    fold: int
    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    chosen: str                 # label picked in-sample
    is_return_pct: float        # the chosen config's IS return
    oos_return_pct: float       # same config, out-of-sample
    oos_buy_hold_pct: float
    oos_excess_pct: float
    oos_trades: int


@dataclass
class WalkForwardResult:
    symbol: str = ""
    timeframe: str = ""
    folds: list = field(default_factory=list)
    n_folds: int = 0
    avg_is_return: float = 0.0
    avg_oos_return: float = 0.0
    avg_oos_excess: float = 0.0
    degradation_pct: float = 0.0     # avg_is - avg_oos (how much edge evaporates OOS)
    oos_positive_folds: int = 0      # folds where OOS return > 0
    oos_beat_bh_folds: int = 0       # folds where OOS beat buy-and-hold
    verdict: str = ""
    error: str = ""


def _score(res: BacktestResult) -> float:
    """In-sample selection metric. Favor risk-adjusted consistency, not raw return:
    profit factor weighted by trade count, penalized by drawdown. Requires a
    minimum number of trades so we don't pick a 1-trade fluke."""
    if res.n_trades < 3:
        return -1e9
    pf = min(res.profit_factor, 5.0)  # cap so one outlier can't dominate
    return pf * (1.0 + res.n_trades / 50.0) - res.max_drawdown_pct / 100.0


def walk_forward(
    df: pd.DataFrame,
    candidates: list[Candidate],
    *,
    n_folds: int = 4,
    oos_frac: float = 0.25,     # each OOS slice = this fraction of a fold
    costs: CostModel = CostModel(1.0, 2.0),
    warmup: int = 35,
    symbol: str = "",
    timeframe: str = "",
) -> WalkForwardResult:
    """Rolling walk-forward. Splits df into n_folds; for each fold, optimize on the
    IS part and validate on the OOS part that immediately follows."""
    n = len(df)
    if n < (warmup + 40) or not candidates:
        return WalkForwardResult(symbol=symbol, timeframe=timeframe,
                                 error="insufficient data or no candidates")

    folds: list[FoldResult] = []
    # Anchored-then-rolling: divide the series into n_folds equal OOS blocks at the
    # tail; everything before each OOS block is its IS training window.
    block = n // (n_folds + 1)  # +1 so the first fold has a real IS history
    if block < warmup + 10:
        return WalkForwardResult(symbol=symbol, timeframe=timeframe,
                                 error="window too short for folds")

    for k in range(1, n_folds + 1):
        is_end = block * k
        oos_end = min(block * (k + 1), n)
        is_df = df.iloc[:is_end]
        oos_df = df.iloc[is_end - warmup:oos_end]  # carry warmup bars so indicators are hot
        if len(oos_df) < warmup + 5:
            continue

        # ---- IN-SAMPLE: pick the best candidate (OOS not touched) ----
        best, best_score, best_is = None, -1e18, None
        for c in candidates:
            r = run_backtest(is_df, c.signal_fn, exits=c.exits, costs=costs,
                             warmup=warmup, scenario=c.label)
            s = _score(r)
            if s > best_score:
                best, best_score, best_is = c, s, r
        if best is None:
            continue

        # ---- OUT-OF-SAMPLE: run the frozen pick once ----
        oos = run_backtest(oos_df, best.signal_fn, exits=best.exits, costs=costs,
                           warmup=warmup, scenario=best.label)
        folds.append(FoldResult(
            fold=k,
            is_start=str(is_df.index[0].date()), is_end=str(is_df.index[-1].date()),
            oos_start=str(oos_df.index[warmup].date()) if len(oos_df) > warmup else str(oos_df.index[-1].date()),
            oos_end=str(oos_df.index[-1].date()),
            chosen=best.label,
            is_return_pct=round(best_is.total_return_pct, 2),
            oos_return_pct=round(oos.total_return_pct, 2),
            oos_buy_hold_pct=round(oos.buy_hold_pct, 2),
            oos_excess_pct=round(oos.excess_vs_buy_hold, 2),
            oos_trades=oos.n_trades,
        ))

    if not folds:
        return WalkForwardResult(symbol=symbol, timeframe=timeframe, error="no valid folds")

    avg_is = sum(f.is_return_pct for f in folds) / len(folds)
    avg_oos = sum(f.oos_return_pct for f in folds) / len(folds)
    avg_exc = sum(f.oos_excess_pct for f in folds) / len(folds)
    pos = sum(1 for f in folds if f.oos_return_pct > 0)
    beat = sum(1 for f in folds if f.oos_excess_pct > 0)
    degr = avg_is - avg_oos

    if avg_oos > 0 and beat >= len(folds) / 2:
        verdict = "Holds up out-of-sample (cautiously usable)."
    elif avg_oos > 0:
        verdict = "Positive OOS but rarely beats buy-and-hold."
    else:
        verdict = "Edge does NOT survive out-of-sample (likely overfit)."

    return WalkForwardResult(
        symbol=symbol, timeframe=timeframe, folds=folds, n_folds=len(folds),
        avg_is_return=round(avg_is, 2), avg_oos_return=round(avg_oos, 2),
        avg_oos_excess=round(avg_exc, 2), degradation_pct=round(degr, 2),
        oos_positive_folds=pos, oos_beat_bh_folds=beat, verdict=verdict,
    )
