"""Portfolio backtest engine — rank -> hold-top-N with periodic rebalancing.

Anti-lookahead contract (mirrors engine.py):
  * The strategy sees frames truncated to <= the rebalance date.
  * New weights take effect from the NEXT trading day's return onward.
Costs: cost_bps charged on turnover sum(|w_new - w_old|) at each rebalance.
Weights are held constant between rebalances (daily-rebalanced-to-target
approximation — fine for monthly cadence, documented here on purpose).

Pure: frames + strategy in, PortfolioResult out. No network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class PortfolioResult:
    strategy: str = ""
    n_rebalances: int = 0
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe: float = 0.0               # annualized, from daily returns
    max_drawdown_pct: float = 0.0
    avg_turnover: float = 0.0         # mean sum|dw| per rebalance
    equity_curve: list = field(default_factory=list)   # [(iso_date, equity)]
    daily_returns: list = field(default_factory=list)
    yearly: dict = field(default_factory=dict)          # year -> return_pct
    error: str = ""


def run_portfolio_backtest(
    frames: dict,
    strategy,
    *,
    cost_bps: float = 5.0,
    rebalance_freq: str = "ME",       # pandas offset: month-end
    config: dict | None = None,
) -> PortfolioResult:
    from backend.strategy.base import UniverseContext

    config = config or {}
    if not frames:
        return PortfolioResult(strategy=getattr(strategy, "name", "?"), error="no data")

    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()
    closes = closes.dropna(how="all")
    if len(closes) < 60:
        return PortfolioResult(strategy=strategy.name, error="insufficient data")
    rets = closes.pct_change().fillna(0.0)

    # Rebalance on the last trading day of each period present in the data.
    # Use "M" period for groupby (works on tz-aware index via to_period conversion).
    # Remove tz before to_period to avoid FutureWarning in pandas >= 2.2.
    period = "M" if rebalance_freq in ("M", "ME") else rebalance_freq
    closes_tz_naive = closes.copy()
    closes_tz_naive.index = closes_tz_naive.index.tz_localize(None) if closes_tz_naive.index.tz is None else closes_tz_naive.index.tz_convert(None)
    marks = closes_tz_naive.groupby(closes_tz_naive.index.to_period(period)).tail(1).index
    # Recover the original tz-aware index values by position
    marks_positions = [closes_tz_naive.index.get_loc(m) for m in marks]
    marks_aware = closes.index[marks_positions]
    rebal_dates = set(marks_aware[:-1])     # last period end has no next day to trade

    weights: dict = {}
    equity = 1.0
    peak, max_dd = 1.0, 0.0
    curve, daily, turnovers = [], [], []
    n_rebal = 0

    dates = list(closes.index)
    for t, dt in enumerate(dates):
        # 1) earn today's return with weights decided strictly BEFORE today
        day_ret = sum(w * float(rets[s].iloc[t]) for s, w in weights.items() if s in rets.columns)
        equity *= (1.0 + day_ret)
        daily.append(day_ret)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((str(dt.date()), round(equity, 6)))

        # 2) if today is a rebalance mark, compute new weights from data <= today;
        #    they apply from tomorrow (loop order enforces this).
        if dt in rebal_dates:
            ctx = UniverseContext(
                date=dt,
                frames={s: f.loc[:dt] for s, f in frames.items()},
                config=config,
            )
            try:
                new_w = strategy.rebalance(ctx) or {}
            except Exception as exc:   # noqa: BLE001 — bubble as result error
                return PortfolioResult(strategy=strategy.name,
                                       error=f"rebalance raised: {exc}")
            turnover = sum(abs(new_w.get(s, 0.0) - weights.get(s, 0.0))
                           for s in set(new_w) | set(weights))
            equity *= (1.0 - turnover * cost_bps / 10_000.0)
            turnovers.append(turnover)
            weights = dict(new_w)
            n_rebal += 1

    total = (equity - 1.0) * 100.0
    years = max(len(dates) / 252.0, 1e-9)
    annual = ((equity ** (1 / years)) - 1.0) * 100.0 if equity > 0 else -100.0
    s = pd.Series(daily)
    sharpe = float(s.mean() / s.std() * (252 ** 0.5)) if s.std() > 0 else 0.0

    yearly: dict = {}
    eq = pd.Series([e for _, e in curve],
                   index=pd.to_datetime([d for d, _ in curve]))
    for year, grp in eq.groupby(eq.index.year):
        yearly[int(year)] = round((grp.iloc[-1] / grp.iloc[0] - 1.0) * 100.0, 2)

    return PortfolioResult(
        strategy=strategy.name, n_rebalances=n_rebal,
        total_return_pct=round(total, 3), annual_return_pct=round(annual, 3),
        sharpe=round(sharpe, 3), max_drawdown_pct=round(max_dd * 100.0, 3),
        avg_turnover=round(sum(turnovers) / len(turnovers), 4) if turnovers else 0.0,
        equity_curve=curve, daily_returns=daily, yearly=yearly,
    )
