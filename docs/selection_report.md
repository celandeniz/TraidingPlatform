# Symbol Selection — trade only OOS-robust names

Whitelist a symbol only if regime-filtered walk-forward gives it positive
out-of-sample return AND it beats buy-and-hold in >=half the folds.

```
[data] AAPL: 3000 bars
[data] MSFT: 3000 bars
[data] GOOGL: 3000 bars
[data] AMZN: 3000 bars
[data] NVDA: 3000 bars
[data] META: 3000 bars
[data] TSLA: 3000 bars

=== Symbol selection (regime-filtered WF, 4 folds) ===
  [excluded ] NVDA   OOS +0.55% (>0), beat B&H 1/4 (<0.5)
  [TRADABLE ] META   OOS +0.50% (>0), beat B&H 3/4 (>=0.5)
  [excluded ] AAPL   OOS -0.77% (<=0), beat B&H 1/4 (<0.5)
  [excluded ] TSLA   OOS -0.98% (<=0), beat B&H 2/4 (>=0.5)
  [excluded ] GOOGL  OOS -1.12% (<=0), beat B&H 1/4 (<0.5)
  [excluded ] MSFT   OOS -1.14% (<=0), beat B&H 1/4 (<0.5)
  [excluded ] AMZN   OOS -1.98% (<=0), beat B&H 1/4 (<0.5)

TRADABLE: ['META']
EXCLUDED: ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA']
portfolio avg OOS — all symbols: -0.71%  |  tradable only: +0.50%

=== Selection-level OUT-OF-SAMPLE validation ===
(derive whitelist on EARLY half, test those names on the LATER half)
  early tradable : []
  early excluded : ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']
  LATE OOS of chosen   : None
  LATE OOS of excluded : -0.75
  selection edge       : None pp
  VERDICT: Inconclusive (too few symbols).
```

## Honest read
- Mechanically it works: only **META** clears the bar; filtering the portfolio
  from -0.71% (all symbols) to **+0.50%** (tradable only).
- BUT the selection-level OOS validation is **inconclusive**: deriving the
  whitelist on the early half yields **zero** tradable names, so we can't show
  that 'chosen' symbols beat 'excluded' ones in a later window.
- **Conclusion:** with one month of 5m data, symbol selection does NOT reliably
  predict future winners. One symbol passing is within noise. Need much longer
  history (SIP feed) for the selection itself to be trustworthy.
