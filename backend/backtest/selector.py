"""Symbol selector — trade only the names that hold up out-of-sample.

Runs regime-filtered walk-forward per symbol and keeps a symbol on the tradable
whitelist only if its OOS performance clears a bar:
  * avg OOS return > min_oos_return  (default 0: net-positive out-of-sample), AND
  * OOS beat buy-and-hold in >= min_beat_frac of folds  (default 0.5).

This is itself a selection on PAST data, so it can overfit too. The honest check
(validate_selection) re-derives the whitelist on an EARLY slice and measures how
those same symbols do on a strictly LATER slice — selection-level out-of-sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..strategy.donchian_breakout import generate as donch
from ..strategy.ema_momentum import generate as ema
from ..strategy.spike_fade import generate as spike
from .engine import ExitParams
from .regime_filter import range_only, with_trend
from .walkforward import Candidate, WalkForwardResult, walk_forward

_EX = ExitParams(2.0, 1.5, 0.8, 90, True)


def improved_candidates() -> list[Candidate]:
    """Regime-aligned set (the (A) improvement)."""
    out = []
    for ze in (1.5, 2.0):
        for k in (2, 3):
            base = lambda d, ze=ze, k=k: spike(d, zscore_window=20, lookback_k=k, z_entry=ze)
            out.append(Candidate(f"sfR_z{ze}_k{k}", range_only(base), _EX))
    for f, s in [(8, 21), (12, 26), (9, 30)]:
        base = lambda d, f=f, s=s: ema(d, fast=f, slow=s)
        out.append(Candidate(f"emaT_{f}_{s}", with_trend(base), _EX))
    for ch in (10, 20, 30):
        base = lambda d, ch=ch: donch(d, channel=ch)
        out.append(Candidate(f"donT_{ch}", with_trend(base), _EX))
    return out


@dataclass
class SymbolVerdict:
    symbol: str
    tradable: bool
    avg_oos_return: float
    oos_beat_bh_folds: int
    n_folds: int
    reason: str


@dataclass
class SelectionResult:
    verdicts: list = field(default_factory=list)
    tradable: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    # portfolio OOS averaged over the chosen names vs all names
    all_avg_oos: float = 0.0
    tradable_avg_oos: float = 0.0


def select_symbols(
    data: dict[str, pd.DataFrame], *, n_folds: int = 4,
    min_oos_return: float = 0.0, min_beat_frac: float = 0.5,
) -> SelectionResult:
    """data: {symbol: df}. Returns the tradable whitelist + per-symbol verdicts."""
    verdicts: list[SymbolVerdict] = []
    cands = improved_candidates()
    all_oos, trad_oos = [], []
    for sym, df in data.items():
        wf: WalkForwardResult = walk_forward(df, cands, n_folds=n_folds, symbol=sym, timeframe="5m")
        if wf.error or not wf.n_folds:
            verdicts.append(SymbolVerdict(sym, False, 0.0, 0, 0, wf.error or "no folds"))
            continue
        all_oos.append(wf.avg_oos_return)
        beat_ok = wf.oos_beat_bh_folds >= min_beat_frac * wf.n_folds
        ret_ok = wf.avg_oos_return > min_oos_return
        tradable = beat_ok and ret_ok
        if tradable:
            trad_oos.append(wf.avg_oos_return)
        reason = (f"OOS {wf.avg_oos_return:+.2f}% "
                  f"({'>' if ret_ok else '<='}{min_oos_return:g}), beat B&H "
                  f"{wf.oos_beat_bh_folds}/{wf.n_folds} "
                  f"({'>=' if beat_ok else '<'}{min_beat_frac:g})")
        verdicts.append(SymbolVerdict(sym, tradable, round(wf.avg_oos_return, 2),
                                      wf.oos_beat_bh_folds, wf.n_folds, reason))
    tradable = [v.symbol for v in verdicts if v.tradable]
    excluded = [v.symbol for v in verdicts if not v.tradable]
    return SelectionResult(
        verdicts=verdicts, tradable=tradable, excluded=excluded,
        all_avg_oos=round(sum(all_oos) / len(all_oos), 2) if all_oos else 0.0,
        tradable_avg_oos=round(sum(trad_oos) / len(trad_oos), 2) if trad_oos else 0.0,
    )


def validate_selection(data: dict[str, pd.DataFrame], *, n_folds: int = 3) -> dict:
    """Selection-level out-of-sample test: derive the whitelist on the EARLY half,
    then measure those symbols on the strictly LATER half. If selection has real
    predictive value, the early-chosen names should still do better late."""
    early, late = {}, {}
    for sym, df in data.items():
        if len(df) < 200:
            continue
        mid = len(df) // 2
        early[sym] = df.iloc[:mid]
        late[sym] = df.iloc[mid:]
    sel_early = select_symbols(early, n_folds=n_folds)
    # how do early-chosen vs early-excluded perform in the LATE window?
    cands = improved_candidates()
    late_oos = {}
    for sym, df in late.items():
        wf = walk_forward(df, cands, n_folds=n_folds, symbol=sym, timeframe="5m")
        late_oos[sym] = None if wf.error else wf.avg_oos_return
    chosen = [late_oos[s] for s in sel_early.tradable if late_oos.get(s) is not None]
    rest = [late_oos[s] for s in sel_early.excluded if late_oos.get(s) is not None]
    chosen_avg = round(sum(chosen) / len(chosen), 2) if chosen else None
    rest_avg = round(sum(rest) / len(rest), 2) if rest else None
    edge = (chosen_avg - rest_avg) if (chosen_avg is not None and rest_avg is not None) else None
    return {
        "early_tradable": sel_early.tradable, "early_excluded": sel_early.excluded,
        "late_oos_of_chosen": chosen_avg, "late_oos_of_excluded": rest_avg,
        "selection_edge_pp": round(edge, 2) if edge is not None else None,
        "verdict": ("Selection has predictive value (chosen beat excluded late)."
                    if edge and edge > 0 else
                    "Selection does NOT predict future winners (honest)."
                    if edge is not None else "Inconclusive (too few symbols)."),
    }
