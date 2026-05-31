# Walk-Forward — (A) Regime Filter + (B) Robustness

Method: chronological IS->OOS, optimize in-sample, validate out-of-sample (no leakage).
The (A) regime filter aligns each strategy with its regime: spike-fade range-only,
ema/donchian with-trend. (B) repeats the improved set across fold counts.

```
=== (A) Regime filter: baseline vs improved (4 folds, 5m) ===

BASELINE                     avg IS +0.02% -> avg OOS -2.43% (degr +2.46pp) | OOS excess -4.20% | beat B&H 8/28 (29%)
IMPROVED (regime-filtered)   avg IS +0.90% -> avg OOS -0.71% (degr +1.61pp) | OOS excess -2.47% | beat B&H 10/28 (36%)

DELTA (improved - baseline): OOS +1.73pp | beat-B&H rate +7pp
VERDICT: regime filter HELPS out-of-sample.

=== (B) Robustness: improved candidates across fold counts ===

3 folds: avg OOS -0.72% | beat B&H 5/21 (24%)
4 folds: avg OOS -0.71% | beat B&H 10/28 (36%)
5 folds: avg OOS -0.51% | beat B&H 12/35 (34%)

OOS-positive symbols (improved, 4-fold): ['NVDA', 'META']
```

## Honest read
- The regime filter **improves** OOS (avg -2.43% -> -0.71%, beat-B&H 29% -> 36%) and
  turns NVDA & META OOS-positive — directionally correct.
- But the portfolio is **still net-negative out-of-sample**: not forward-tradable as-is.
- Result is **stable across 3/4/5 folds**, so it's not a fold-count artifact.
- Next levers: longer history (SIP feed), per-symbol selection (trade only OOS-robust
  names like NVDA/META), or accept these are research signals, not a live edge yet.
