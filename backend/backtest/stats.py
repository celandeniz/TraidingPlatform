"""Statistical significance for backtest trade returns — guard against fooling
ourselves with noise.

A handful of trades with a positive average tells you almost nothing: the result
could be pure luck. These tools quantify that:

  * t_statistic / p_value: is the mean per-trade return distinguishable from zero?
  * bootstrap_ci: resample the trades to get a confidence interval on the mean —
    if the interval straddles 0, the edge is not established.
  * significance_label: a plain-language verdict combining sample size + p-value.

Pure functions; deterministic bootstrap (seeded). No SciPy dependency — the
t-distribution p-value uses a normal approximation (fine for n>=~20; flagged as
small-sample otherwise).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Significance:
    n: int
    mean_pct: float
    std_pct: float
    t_stat: float
    p_value: float          # two-sided, approx
    ci_low_pct: float       # bootstrap 95% CI on the mean per-trade return
    ci_high_pct: float
    significant: bool       # p < 0.05 AND n >= 20 AND CI excludes 0
    label: str


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def t_statistic(returns: list[float]) -> tuple[float, float]:
    """Return (t_stat, two-sided p-value approx) for mean(returns) != 0."""
    n = len(returns)
    if n < 2:
        return 0.0, 1.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std == 0:
        return (float("inf") if mean != 0 else 0.0), (0.0 if mean != 0 else 1.0)
    t = mean / (std / math.sqrt(n))
    # two-sided p via normal approx to the t-distribution
    p = 2.0 * (1.0 - _normal_cdf(abs(t)))
    return t, p


def bootstrap_ci(returns: list[float], *, iters: int = 2000, alpha: float = 0.05,
                 seed: int = 12345) -> tuple[float, float]:
    """95% CI on the mean per-trade return via seeded bootstrap resampling."""
    n = len(returns)
    if n < 2:
        return (0.0, 0.0)
    # simple LCG so we don't pull in numpy here and stay deterministic
    state = seed
    def _rand():
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state / 0x7FFFFFFF
    means = []
    for _ in range(iters):
        s = 0.0
        for _ in range(n):
            s += returns[int(_rand() * n) % n]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * iters)]
    hi = means[int((1 - alpha / 2) * iters) - 1]
    return (lo, hi)


def significance(returns: list[float]) -> Significance:
    """Full significance read on a list of per-trade returns (in %)."""
    n = len(returns)
    if n == 0:
        return Significance(0, 0, 0, 0, 1.0, 0, 0, False, "no trades")
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    t, p = t_statistic(returns)
    lo, hi = bootstrap_ci(returns)
    ci_excludes_zero = (lo > 0) or (hi < 0)
    sig = (p < 0.05) and (n >= 20) and ci_excludes_zero
    if n < 20:
        label = f"too few trades (n={n}) — not statistically meaningful"
    elif sig and mean > 0:
        label = f"significant positive edge (p={p:.3f}, n={n})"
    elif sig and mean < 0:
        label = f"significantly negative (p={p:.3f}, n={n})"
    else:
        label = f"not significant — likely noise (p={p:.3f}, n={n})"
    return Significance(
        n=n, mean_pct=round(mean, 3), std_pct=round(std, 3), t_stat=round(t, 3),
        p_value=round(p, 4), ci_low_pct=round(lo, 3), ci_high_pct=round(hi, 3),
        significant=sig, label=label,
    )
