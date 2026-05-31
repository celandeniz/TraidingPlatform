"""Walk-forward over the M7 symbols — does the edge survive out-of-sample?

    .venv/bin/python -m backend.backtest.run_walkforward [folds]
"""
from __future__ import annotations

import sys

from ..data.alpaca_provider import AlpacaProvider
from ..settings import get_config, get_settings
from ..strategy.donchian_breakout import generate as donch
from ..strategy.ema_momentum import generate as ema
from ..strategy.spike_fade import generate as spike
from .engine import ExitParams
from .walkforward import Candidate, walk_forward


def candidate_set() -> list[Candidate]:
    """A spread of strategies/params the IS optimizer chooses among each fold."""
    cands = []
    for ze in (1.5, 2.0):
        for k in (2, 3):
            cands.append(Candidate(
                f"sf_z{ze}_k{k}",
                lambda df, ze=ze, k=k: spike(df, zscore_window=20, lookback_k=k, z_entry=ze),
                ExitParams(2.0, 1.5, 0.8, 90, True)))
    for f, s in [(8, 21), (12, 26), (9, 30)]:
        cands.append(Candidate(f"ema_{f}_{s}",
                               lambda df, f=f, s=s: ema(df, fast=f, slow=s),
                               ExitParams(2.0, 1.5, 0.8, 90, True)))
    for ch in (10, 20, 30):
        cands.append(Candidate(f"don_{ch}",
                               lambda df, ch=ch: donch(df, channel=ch),
                               ExitParams(2.0, 1.5, 0.8, 90, True)))
    return cands


def main():
    folds = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    s = get_settings(); cfg = get_config()
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    cands = candidate_set()
    print(f"[walk-forward] {len(cands)} candidates | {folds} folds | 5m | "
          f"IS-optimize -> OOS-validate (no leakage)\n")

    overall = []
    for sym in cfg["universe"]:
        df = provider.get_recent_bars(sym, "5m", 3000)
        wf = walk_forward(df, cands, n_folds=folds, symbol=sym, timeframe="5m")
        if wf.error:
            print(f"{sym}: {wf.error}"); continue
        overall.append(wf)
        print(f"=== {sym} 5m ===  {wf.verdict}")
        print(f"  avg IS {wf.avg_is_return:+.2f}% -> avg OOS {wf.avg_oos_return:+.2f}% "
              f"(degradation {wf.degradation_pct:+.2f}pp) | OOS excess {wf.avg_oos_excess:+.2f}% "
              f"| OOS+ folds {wf.oos_positive_folds}/{wf.n_folds} | beat B&H {wf.oos_beat_bh_folds}/{wf.n_folds}")
        for f in wf.folds:
            print(f"    fold {f.fold}: chose {f.chosen:<10} IS {f.is_return_pct:+6.2f}% "
                  f"-> OOS {f.oos_return_pct:+6.2f}% (B&H {f.oos_buy_hold_pct:+6.2f}%, "
                  f"excess {f.oos_excess_pct:+6.2f}%, {f.oos_trades} trades) "
                  f"[OOS {f.oos_start}..{f.oos_end}]")
        print()

    if overall:
        ais = sum(w.avg_is_return for w in overall) / len(overall)
        aoos = sum(w.avg_oos_return for w in overall) / len(overall)
        beat = sum(w.oos_beat_bh_folds for w in overall)
        tot = sum(w.n_folds for w in overall)
        print(f"PORTFOLIO: avg IS {ais:+.2f}% -> avg OOS {aoos:+.2f}% "
              f"(degradation {ais-aoos:+.2f}pp) | OOS beat-B&H {beat}/{tot} folds "
              f"({beat/max(tot,1)*100:.0f}%)")
    return overall


if __name__ == "__main__":
    main()
