"""Pairs stat-arb engine: cointegration selection + spread z-score backtest.

Selection: candidate pairs by close-price correlation, then Engle-Granger
cointegration (statsmodels coint); keep the strongest by p-value, annotated with
the spread's AR(1) mean-reversion half-life.

Backtest (daily): rolling OLS hedge ratio over hedge_window; spread z-score over
the same window. Enter long-spread at z <= -z_entry (buy A, sell B*beta), short-
spread at z >= +z_entry; exit at z crossing z_exit; stop at |z| >= z_stop or
max_days. Both legs dollar-neutral; cost_bps charged per leg per side.
Anti-lookahead: signals use data through day t; fills at day t+1's open.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PairSpec:
    sym_a: str
    sym_b: str
    pvalue: float
    half_life: float


def _half_life(spread: pd.Series) -> float:
    s = spread.dropna()
    lag, diff = s.shift(1).iloc[1:], s.diff().iloc[1:]
    beta = np.polyfit(lag, diff, 1)[0]
    if beta >= 0:
        return float("inf")
    return float(-np.log(2) / beta)


def find_pairs(frames: dict, *, corr_min: float = 0.8, pval_max: float = 0.05,
               top_n: int = 10) -> list[PairSpec]:
    from statsmodels.tsa.stattools import coint

    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).dropna()
    syms = list(closes.columns)
    corr = closes.corr()
    out: list[PairSpec] = []
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            if corr.loc[a, b] < corr_min:
                continue
            _, pval, _ = coint(closes[a], closes[b])
            if pval >= pval_max:
                continue
            beta = float(np.polyfit(closes[b], closes[a], 1)[0])
            out.append(PairSpec(a, b, float(pval),
                                _half_life(closes[a] - beta * closes[b])))
    out.sort(key=lambda p: p.pvalue)
    return out[:top_n]


def run_pairs_backtest(df_a: pd.DataFrame, df_b: pd.DataFrame, *,
                       z_entry: float = 2.0, z_exit: float = 0.0,
                       z_stop: float = 3.5, max_days: int = 30,
                       hedge_window: int = 60, cost_bps: float = 3.0) -> dict:
    a, b = df_a["close"].align(df_b["close"], join="inner")
    oa, ob = df_a["open"].reindex(a.index), df_b["open"].reindex(b.index)
    n = len(a)
    if n < hedge_window + 10:
        return {"n_trades": 0, "total_return_pct": 0.0, "trades": [],
                "error": "insufficient data"}

    cost = cost_bps / 10_000.0
    equity, curve = 1.0, [1.0]
    trades: list[dict] = []
    pos = None   # dict(side, i0, pa, pb, beta_w)

    for t in range(hedge_window, n - 1):
        wa, wb = a.iloc[t - hedge_window:t + 1], b.iloc[t - hedge_window:t + 1]
        beta = float(np.polyfit(wb, wa, 1)[0])
        spread = wa - beta * wb
        mu, sd = float(spread.mean()), float(spread.std())
        if sd == 0:
            continue
        z = (float(spread.iloc[-1]) - mu) / sd

        if pos is not None:
            held = t - pos["i0"]
            crossed = (pos["side"] == "long" and z >= z_exit) or \
                      (pos["side"] == "short" and z <= z_exit)
            stopped = abs(z) >= z_stop or held >= max_days
            if crossed or stopped:
                # exit fills at NEXT open
                xa, xb = float(oa.iloc[t + 1]), float(ob.iloc[t + 1])
                sgn = 1.0 if pos["side"] == "long" else -1.0
                ret_a = sgn * (xa / pos["pa"] - 1.0)
                ret_b = -sgn * pos["beta_w"] * (xb / pos["pb"] - 1.0)
                ret = (ret_a + ret_b) / (1.0 + pos["beta_w"]) - 4 * cost
                equity *= (1.0 + ret)
                curve.append(equity)
                trades.append({"side": pos["side"], "entry_idx": pos["i0"],
                               "exit_idx": t + 1, "bars_held": held,
                               "reason": "z_exit" if crossed else
                                         ("z_stop" if abs(z) >= z_stop else "time_stop"),
                               "ret_pct": ret * 100.0})
                pos = None
                continue

        if pos is None and abs(z) >= z_entry:
            pa, pb = float(oa.iloc[t + 1]), float(ob.iloc[t + 1])  # next-open fill
            # dollar-neutral leg weights: 1 unit A vs beta-adjusted notional B
            beta_w = abs(beta) * pb / pa if pa > 0 else 1.0
            pos = {"side": "long" if z <= -z_entry else "short",
                   "i0": t + 1, "pa": pa, "pb": pb, "beta_w": beta_w}

    peak, max_dd = 1.0, 0.0
    for e in curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    return {"n_trades": len(trades), "total_return_pct": (equity - 1.0) * 100.0,
            "max_drawdown_pct": max_dd * 100.0, "trades": trades, "error": ""}
