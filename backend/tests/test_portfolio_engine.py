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


# ---------------------------------------------------------------------------
# Issue 1: costs must land in daily_returns so Sharpe / max_drawdown are net
# ---------------------------------------------------------------------------

class Churner:
    """Alternates between WIN and LOSE each rebalance — maximum possible turnover."""
    name = "churner"

    def rebalance(self, ctx):
        # odd month -> WIN, even month -> LOSE (churns at every rebalance)
        if ctx.date.month % 2 == 1:
            return {"WIN": 1.0}
        return {"LOSE": 1.0}


def test_costs_degrade_sharpe_and_drawdown():
    import math
    frames = _frames()

    res_free = run_portfolio_backtest(frames, Churner(), cost_bps=0.0)
    res_costly = run_portfolio_backtest(frames, Churner(), cost_bps=100.0)

    assert res_free.error == ""
    assert res_costly.error == ""

    # Costs must reduce Sharpe
    assert res_costly.sharpe < res_free.sharpe, (
        f"sharpe with costs ({res_costly.sharpe}) should be < free ({res_free.sharpe})"
    )

    # Costs must equal or worsen max drawdown
    assert res_costly.max_drawdown_pct >= res_free.max_drawdown_pct, (
        f"max_dd with costs ({res_costly.max_drawdown_pct}) should be >= free ({res_free.max_drawdown_pct})"
    )

    # Key invariant: daily_returns must reproduce equity exactly
    for res in (res_free, res_costly):
        compounded = math.prod(1.0 + r for r in res.daily_returns)
        expected = 1.0 + res.total_return_pct / 100.0
        assert compounded == pytest.approx(expected, rel=1e-9), (
            f"daily_returns compounded ({compounded}) != final equity ({expected})"
        )


# ---------------------------------------------------------------------------
# Issue 2: weight sanitization
# ---------------------------------------------------------------------------

class LeveragedWinner:
    name = "leveraged_winner"
    def rebalance(self, ctx):
        return {"WIN": 3.0}   # leverage — must be scaled to 1.0


class NegativeWeightStrategy:
    name = "negative_weight"
    def rebalance(self, ctx):
        return {"WIN": 1.0, "LOSE": -1.0}   # short — LOSE weight must be clamped to 0


def test_leveraged_weights_scaled_to_one():
    frames = _frames()
    res_normal = run_portfolio_backtest(frames, AlwaysWinner(), cost_bps=0.0)
    res_leveraged = run_portfolio_backtest(frames, LeveragedWinner(), cost_bps=0.0)
    # After sanitization 3x WIN -> 1x WIN; results must be identical
    assert res_leveraged.total_return_pct == pytest.approx(res_normal.total_return_pct, rel=1e-6)
    assert res_leveraged.sharpe == pytest.approx(res_normal.sharpe, rel=1e-6)


def test_negative_weights_clamped():
    frames = _frames()
    res_normal = run_portfolio_backtest(frames, AlwaysWinner(), cost_bps=0.0)
    res_negative = run_portfolio_backtest(frames, NegativeWeightStrategy(), cost_bps=0.0)
    # LOSE is clamped to 0; WIN=1.0 passes sum check — results must match AlwaysWinner
    assert res_negative.total_return_pct == pytest.approx(res_normal.total_return_pct, rel=1e-6)
    assert res_negative.sharpe == pytest.approx(res_normal.sharpe, rel=1e-6)
