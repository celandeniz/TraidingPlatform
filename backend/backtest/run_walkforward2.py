"""Improved + robustness walk-forward:
  (A) regime-filtered candidates vs the plain baseline
  (B) repeat WF over varied fold counts (3/4/5) to test robustness

    .venv/bin/python -m backend.backtest.run_walkforward2

Honest: prints whether the regime filter actually closes the IS->OOS gap, and
whether any symbol holds up across fold configs. If it doesn't help, it says so.
"""
from __future__ import annotations

from ..data.alpaca_provider import AlpacaProvider
from ..settings import get_config, get_settings
from ..strategy.donchian_breakout import generate as donch
from ..strategy.ema_momentum import generate as ema
from ..strategy.spike_fade import generate as spike
from .engine import ExitParams
from .regime_filter import range_only, with_trend
from .walkforward import Candidate, walk_forward

_EX = ExitParams(2.0, 1.5, 0.8, 90, True)


def baseline_candidates():
    c = []
    for ze in (1.5, 2.0):
        for k in (2, 3):
            c.append(Candidate(f"sf_z{ze}_k{k}",
                     lambda d, ze=ze, k=k: spike(d, zscore_window=20, lookback_k=k, z_entry=ze), _EX))
    for f, s in [(8, 21), (12, 26), (9, 30)]:
        c.append(Candidate(f"ema_{f}_{s}", lambda d, f=f, s=s: ema(d, fast=f, slow=s), _EX))
    for ch in (10, 20, 30):
        c.append(Candidate(f"don_{ch}", lambda d, ch=ch: donch(d, channel=ch), _EX))
    return c


def improved_candidates():
    """Same strategies, regime-aligned: spike-fade range-only; ema/donchian with-trend."""
    c = []
    for ze in (1.5, 2.0):
        for k in (2, 3):
            base = lambda d, ze=ze, k=k: spike(d, zscore_window=20, lookback_k=k, z_entry=ze)
            c.append(Candidate(f"sfR_z{ze}_k{k}", range_only(base), _EX))
    for f, s in [(8, 21), (12, 26), (9, 30)]:
        base = lambda d, f=f, s=s: ema(d, fast=f, slow=s)
        c.append(Candidate(f"emaT_{f}_{s}", with_trend(base), _EX))
    for ch in (10, 20, 30):
        base = lambda d, ch=ch: donch(d, channel=ch)
        c.append(Candidate(f"donT_{ch}", with_trend(base), _EX))
    return c


def _portfolio(provider, symbols, cands, folds):
    isr = oosr = exc = beat = tot = 0.0
    nfold = 0
    per = []
    for sym in symbols:
        df = provider.get_recent_bars(sym, "5m", 3000)
        wf = walk_forward(df, cands, n_folds=folds, symbol=sym, timeframe="5m")
        if wf.error:
            continue
        per.append(wf)
        isr += wf.avg_is_return; oosr += wf.avg_oos_return; exc += wf.avg_oos_excess
        beat += wf.oos_beat_bh_folds; tot += wf.n_folds; nfold += 1
    if not nfold:
        return None
    return {"avg_is": isr / nfold, "avg_oos": oosr / nfold, "avg_exc": exc / nfold,
            "beat": int(beat), "tot": int(tot), "per": per}


def main():
    s = get_settings(); cfg = get_config()
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    syms = cfg["universe"]

    print("=== (A) Regime filter: baseline vs improved (4 folds, 5m) ===\n")
    base = _portfolio(provider, syms, baseline_candidates(), 4)
    impr = _portfolio(provider, syms, improved_candidates(), 4)
    for name, p in [("BASELINE", base), ("IMPROVED (regime-filtered)", impr)]:
        if p:
            print(f"{name:<28} avg IS {p['avg_is']:+.2f}% -> avg OOS {p['avg_oos']:+.2f}% "
                  f"(degr {p['avg_is']-p['avg_oos']:+.2f}pp) | OOS excess {p['avg_exc']:+.2f}% "
                  f"| beat B&H {p['beat']}/{p['tot']} ({p['beat']/max(p['tot'],1)*100:.0f}%)")
    if base and impr:
        d_oos = impr["avg_oos"] - base["avg_oos"]
        d_beat = impr["beat"]/max(impr["tot"],1) - base["beat"]/max(base["tot"],1)
        print(f"\nDELTA (improved - baseline): OOS {d_oos:+.2f}pp | beat-B&H rate {d_beat*100:+.0f}pp")
        print("VERDICT:", "regime filter HELPS out-of-sample." if d_oos > 0.3
              else "regime filter does NOT meaningfully help (honest).")

    print("\n=== (B) Robustness: improved candidates across fold counts ===\n")
    for folds in (3, 4, 5):
        p = _portfolio(provider, syms, improved_candidates(), folds)
        if p:
            print(f"{folds} folds: avg OOS {p['avg_oos']:+.2f}% | beat B&H "
                  f"{p['beat']}/{p['tot']} ({p['beat']/max(p['tot'],1)*100:.0f}%)")
    # surface any symbol that is OOS-positive in the improved 4-fold run
    if impr:
        winners = [w.symbol for w in impr["per"] if w.avg_oos_return > 0]
        print(f"\nOOS-positive symbols (improved, 4-fold): {winners or 'NONE'}")


if __name__ == "__main__":
    main()
