# M7 Walk-Forward (Out-of-Sample) Validation

**Method:** chronological IS→OOS split, 4 folds per symbol, 5m bars. The strategy is
optimized IN-SAMPLE (past window) and validated OUT-OF-SAMPLE (next, unseen window).
OOS data never influences the pick. Underlying backtest is no-lookahead.

```
[walk-forward] 10 candidates | 4 folds | 5m | IS-optimize -> OOS-validate (no leakage)

=== AAPL 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS +1.44% -> avg OOS -1.44% (degradation +2.87pp) | OOS excess -4.49% | OOS+ folds 0/4 | beat B&H 1/4
    fold 1: chose don_10     IS  +3.02% -> OOS  -0.69% (B&H  -1.92%, excess  +1.23%, 12 trades) [OOS 2026-04-20..2026-04-30]
    fold 2: chose sf_z1.5_k3 IS  +3.08% -> OOS  -3.10% (B&H  +7.61%, excess -10.71%, 12 trades) [OOS 2026-04-30..2026-05-11]
    fold 3: chose sf_z1.5_k2 IS  +2.20% -> OOS  -1.01% (B&H  +2.18%, excess  -3.18%, 2 trades) [OOS 2026-05-11..2026-05-20]
    fold 4: chose don_10     IS  -2.56% -> OOS  -0.95% (B&H  +4.34%, excess  -5.29%, 12 trades) [OOS 2026-05-20..2026-05-29]

=== MSFT 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS +0.72% -> avg OOS -1.68% (degradation +2.40pp) | OOS excess -3.10% | OOS+ folds 0/4 | beat B&H 1/4
    fold 1: chose sf_z1.5_k2 IS  +1.84% -> OOS  -1.21% (B&H  -0.18%, excess  -1.03%, 4 trades) [OOS 2026-04-20..2026-04-29]
    fold 2: chose sf_z2.0_k3 IS  +2.15% -> OOS  -0.31% (B&H  -1.98%, excess  +1.67%, 5 trades) [OOS 2026-04-29..2026-05-08]
    fold 3: chose sf_z1.5_k2 IS  +3.05% -> OOS  -2.01% (B&H  +0.67%, excess  -2.68%, 7 trades) [OOS 2026-05-08..2026-05-19]
    fold 4: chose don_10     IS  -4.18% -> OOS  -3.20% (B&H  +7.16%, excess -10.36%, 21 trades) [OOS 2026-05-19..2026-05-29]

=== GOOGL 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS +2.43% -> avg OOS -3.02% (degradation +5.46pp) | OOS excess -6.23% | OOS+ folds 0/4 | beat B&H 1/4
    fold 1: chose don_10     IS  +6.03% -> OOS  -3.38% (B&H  +3.80%, excess  -7.18%, 18 trades) [OOS 2026-04-17..2026-04-29]
    fold 2: chose don_20     IS  +3.82% -> OOS  -2.83% (B&H +13.85%, excess -16.69%, 20 trades) [OOS 2026-04-29..2026-05-08]
    fold 3: chose sf_z2.0_k3 IS  +4.05% -> OOS  -2.00% (B&H  -2.70%, excess  +0.71%, 5 trades) [OOS 2026-05-08..2026-05-19]
    fold 4: chose don_10     IS  -4.16% -> OOS  -3.88% (B&H  -2.14%, excess  -1.75%, 19 trades) [OOS 2026-05-19..2026-05-29]

=== AMZN 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS +7.02% -> avg OOS -1.25% (degradation +8.26pp) | OOS excess -2.99% | OOS+ folds 1/4 | beat B&H 1/4
    fold 1: chose sf_z1.5_k3 IS  +1.38% -> OOS  -0.05% (B&H  +3.84%, excess  -3.90%, 11 trades) [OOS 2026-04-16..2026-04-28]
    fold 2: chose ema_8_21   IS +11.81% -> OOS  -4.74% (B&H  +4.62%, excess  -9.36%, 15 trades) [OOS 2026-04-28..2026-05-07]
    fold 3: chose don_10     IS  +6.12% -> OOS  +2.01% (B&H  -5.58%, excess  +7.59%, 14 trades) [OOS 2026-05-07..2026-05-19]
    fold 4: chose don_10     IS  +8.75% -> OOS  -2.21% (B&H  +4.08%, excess  -6.29%, 21 trades) [OOS 2026-05-19..2026-05-29]

=== NVDA 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS +0.00% -> avg OOS -4.18% (degradation +4.18pp) | OOS excess -5.50% | OOS+ folds 0/4 | beat B&H 0/4
    fold 1: chose ema_8_21   IS  +2.57% -> OOS  -0.35% (B&H  +0.26%, excess  -0.62%, 16 trades) [OOS 2026-04-21..2026-04-30]
    fold 2: chose ema_8_21   IS  +2.20% -> OOS  -2.82% (B&H  +6.64%, excess  -9.46%, 16 trades) [OOS 2026-04-30..2026-05-11]
    fold 3: chose ema_8_21   IS  -0.68% -> OOS  -3.43% (B&H  +3.11%, excess  -6.54%, 19 trades) [OOS 2026-05-11..2026-05-20]
    fold 4: chose ema_9_30   IS  -4.08% -> OOS -10.11% (B&H  -4.75%, excess  -5.36%, 25 trades) [OOS 2026-05-20..2026-05-29]

=== META 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS -4.54% -> avg OOS -3.96% (degradation -0.58pp) | OOS excess -2.37% | OOS+ folds 1/4 | beat B&H 2/4
    fold 1: chose don_10     IS  +2.67% -> OOS  -6.51% (B&H  -0.26%, excess  -6.25%, 21 trades) [OOS 2026-04-17..2026-04-28]
    fold 2: chose don_10     IS  -4.01% -> OOS  -5.57% (B&H  -8.16%, excess  +2.59%, 28 trades) [OOS 2026-04-28..2026-05-08]
    fold 3: chose don_10     IS  -9.18% -> OOS  +1.61% (B&H  -1.65%, excess  +3.26%, 18 trades) [OOS 2026-05-08..2026-05-19]
    fold 4: chose don_10     IS  -7.64% -> OOS  -5.37% (B&H  +3.71%, excess  -9.08%, 19 trades) [OOS 2026-05-19..2026-05-29]

=== TSLA 5m ===  Edge does NOT survive out-of-sample (likely overfit).
  avg IS -6.90% -> avg OOS -1.51% (degradation -5.39pp) | OOS excess -4.74% | OOS+ folds 1/4 | beat B&H 2/4
    fold 1: chose sf_z2.0_k2 IS  +0.32% -> OOS  +0.16% (B&H  -4.58%, excess  +4.74%, 6 trades) [OOS 2026-04-20..2026-04-29]
    fold 2: chose sf_z2.0_k2 IS  +0.49% -> OOS  -1.52% (B&H +14.86%, excess -16.38%, 9 trades) [OOS 2026-04-29..2026-05-08]
    fold 3: chose don_10     IS -13.59% -> OOS  -1.39% (B&H  -5.46%, excess  +4.06%, 39 trades) [OOS 2026-05-08..2026-05-19]
    fold 4: chose don_10     IS -14.80% -> OOS  -3.28% (B&H  +8.11%, excess -11.39%, 29 trades) [OOS 2026-05-19..2026-05-29]

PORTFOLIO: avg IS +0.02% -> avg OOS -2.43% (degradation +2.46pp) | OOS beat-B&H 8/28 folds (29%)
```
