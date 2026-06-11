"""Portfolio engine: rank -> hold-top-N rebalancing on daily bars, no lookahead."""
import pandas as pd
import pytest

from backend.backtest.portfolio_engine import run_portfolio_backtest


def _frame(daily_rets: list[float], start="2024-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(daily_rets) + 1, tz="UTC")
    px = [100.0]
    for r in daily_rets:
        px.append(px[-1] * (1 + r))
    s = pd.Series(px, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": 1e6})


class AlwaysWinner:
    name = "always_winner"
    def rebalance(self, ctx):
        return {"WIN": 1.0}


class Peeker:
    """Asserts the engine never hands us bars after the rebalance date."""
    name = "peeker"
    def rebalance(self, ctx):
        for sym, df in ctx.frames.items():
            assert df.index.max() <= ctx.date, f"{sym} leaked future bars"
        return {"WIN": 1.0}


def _frames():
    n = 300
    return {"WIN": _frame([0.002] * n), "LOSE": _frame([-0.002] * n)}


def test_holding_the_winner_makes_money():
    res = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=0.0)
    assert res.error == ""
    assert res.total_return_pct > 20.0
    assert res.n_rebalances >= 10           # ~14 month-ends in 300 bdays
    assert res.max_drawdown_pct < 5.0
    assert len(res.equity_curve) > 200


def test_no_future_bars_reach_the_strategy():
    run_portfolio_backtest(_frames(), Peeker(), cost_bps=0.0)  # Peeker asserts


def test_turnover_costs_reduce_return():
    free = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=0.0)
    costly = run_portfolio_backtest(_frames(), AlwaysWinner(), cost_bps=50.0)
    assert costly.total_return_pct < free.total_return_pct


def test_all_cash_strategy_flat():
    class Cash:
        name = "cash"
        def rebalance(self, ctx):
            return {}
    res = run_portfolio_backtest(_frames(), Cash(), cost_bps=0.0)
    assert abs(res.total_return_pct) < 1e-9
