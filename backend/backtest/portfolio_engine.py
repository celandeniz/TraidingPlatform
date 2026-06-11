"""Portfolio backtest engine — rank -> hold-top-N with periodic rebalancing.

Anti-lookahead contract (mirrors engine.py):
  * The strategy sees frames truncated to <= the rebalance date.
  * New weights take effect from the NEXT trading day's return onward.
Costs: cost_bps charged on turnover sum(|w_new - w_old|) at each rebalance.
  The cost is booked into THAT DAY's return so Sharpe, max_drawdown_pct and
  daily_returns are all net of costs — not gross.
Weights are held constant between rebalances (daily-rebalanced-to-target
approximation — fine for monthly cadence, documented here on purpose).

Known limitation: a symbol whose frame ends early (delisting) earns 0% from
its last bar onward instead of being liquidated — survivorship-safe universes
should be used upstream.

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
    sharpe: float = 0.0               # annualized, from daily returns (net of costs)
    max_drawdown_pct: float = 0.0
    avg_turnover: float = 0.0         # mean sum|dw| per rebalance
    equity_curve: list = field(default_factory=list)   # [(iso_date, equity)]
    daily_returns: list = field(default_factory=list)
    yearly: dict = field(default_factory=dict)          # year -> return_pct
    error: str = ""


def _sanitize_weights(w: dict) -> dict:
    """Return a long-only, fully-invested-cap copy of *w*.

    long-only, fully-invested cap; the tournament engine is not a leverage
    simulator.

    Rules applied in order:
      1. Clamp negative weights to 0.0.
      2. If the remaining sum exceeds 1.0 (beyond 1e-9 float tolerance),
         scale all weights proportionally so they sum to exactly 1.0.
    """
    # Step 1: clamp negatives
    cleaned = {s: max(0.0, v) for s, v in w.items()}
    # Step 2: scale down leverage
    total = sum(cleaned.values())
    if total > 1.0 + 1e-9:
        cleaned = {s: v / total for s, v in cleaned.items()}
    return cleaned


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
    if len(closes) < 60:  # ~3 months of daily bars — too short to mean anything
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
        # Step 1: earn today's return with weights decided strictly BEFORE today.
        day_ret = sum(w * float(rets[s].iloc[t]) for s, w in weights.items() if s in rets.columns)

        # Step 2: if today is a rebalance mark, compute new weights from data <=
        # today and fold the transaction cost INTO today's return.
        # New weights still apply from TOMORROW — only the cost is booked today.
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
            new_w = _sanitize_weights(new_w)
            turnover = sum(abs(new_w.get(s, 0.0) - weights.get(s, 0.0))
                           for s in set(new_w) | set(weights))
            cost = turnover * cost_bps / 10_000.0
            # Book cost into this day's return so metrics are net of costs
            day_ret = (1.0 + day_ret) * (1.0 - cost) - 1.0
            turnovers.append(turnover)
            weights = new_w
            n_rebal += 1

        # Step 3: apply the (possibly cost-adjusted) return to equity and metrics.
        equity *= (1.0 + day_ret)
        daily.append(day_ret)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((str(dt.date()), round(equity, 6)))

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
        # total_return_pct stored at full float precision so that
        # math.prod(1+r for r in daily_returns) == 1 + total_return_pct/100
        # holds to floating-point limits (the daily_returns↔equity identity).
        total_return_pct=total,
        annual_return_pct=round(annual, 3),
        sharpe=round(sharpe, 3), max_drawdown_pct=round(max_dd * 100.0, 3),
        avg_turnover=round(sum(turnovers) / len(turnovers), 4) if turnovers else 0.0,
        equity_curve=curve, daily_returns=daily, yearly=yearly,
    )
