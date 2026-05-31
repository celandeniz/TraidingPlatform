"""Backtest engine tests — the critical guarantees: no lookahead, costs, P&L sign."""
import pandas as pd

from backend.backtest.engine import CostModel, ExitParams, run_backtest
from backend.backtest.analyze import analyze_results


def _df(opens, highs, lows, closes):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": [1000] * n}, index=idx)


def test_no_lookahead_entry_fills_next_bar_open():
    # Signal fires on bar i (warmup); fill must be open[i+1], not close[i].
    n = 40
    closes = [100.0] * n
    opens = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    # make bar 35's NEXT open distinctive so we can detect which bar filled
    opens[36] = 102.0
    fired = {"done": False}

    def sig(df):
        # fire exactly once at index 35
        if len(df) == 36 and not fired["done"]:
            fired["done"] = True
            return {"buy": True, "sell": False}
        return {"buy": False, "sell": False}

    res = run_backtest(_df(opens, highs, lows, closes), sig,
                       exits=ExitParams(99, 99, None, 200, True),
                       costs=CostModel(0, 0), warmup=35)
    assert res.n_trades >= 1
    # entry recorded at index 36 (next bar), filled at open=102.0
    t = res.trades[0]
    assert t.entry_idx == 36
    assert abs(t.entry_px - 102.0) < 1e-6  # next bar's open, no cost here


def test_costs_make_entry_worse():
    n = 40
    opens = [100.0] * n; highs = [100.5] * n; lows = [99.5] * n; closes = [100.0] * n

    def sig(df):
        return {"buy": True, "sell": False} if len(df) == 36 else {"buy": False, "sell": False}

    no_cost = run_backtest(_df(opens, highs, lows, closes), sig,
                           exits=ExitParams(99, 99, None, 200, True),
                           costs=CostModel(0, 0), warmup=35)
    with_cost = run_backtest(_df(opens, highs, lows, closes), sig,
                             exits=ExitParams(99, 99, None, 200, True),
                             costs=CostModel(10, 10), warmup=35)
    # a long entry pays UP with cost
    assert with_cost.trades[0].entry_px > no_cost.trades[0].entry_px


def test_long_take_profit_hits():
    # flat, then an up-move that crosses +1% take-profit after entry
    n = 45
    closes = [100.0] * 36 + [100.0, 100.5, 101.5, 102.0] + [102.0] * 5
    opens = closes[:]
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.3 for c in closes]

    def sig(df):
        return {"buy": True, "sell": False} if len(df) == 36 else {"buy": False, "sell": False}

    res = run_backtest(_df(opens, highs, lows, closes), sig,
                       exits=ExitParams(1.0, 5.0, None, 200, True),
                       costs=CostModel(0, 0), warmup=35)
    assert res.n_trades == 1
    assert res.trades[0].reason == "take_profit"
    assert res.trades[0].ret_pct > 0


def test_short_profits_when_price_falls():
    n = 45
    closes = [100.0] * 36 + [100.0, 99.5, 98.5, 98.0] + [98.0] * 5
    opens = closes[:]
    highs = [c + 0.3 for c in closes]
    lows = [c - 0.6 for c in closes]

    def sig(df):
        return {"buy": False, "sell": True} if len(df) == 36 else {"buy": False, "sell": False}

    res = run_backtest(_df(opens, highs, lows, closes), sig,
                       exits=ExitParams(1.0, 5.0, None, 200, True),
                       costs=CostModel(0, 0), warmup=35)
    assert res.n_trades == 1
    assert res.trades[0].side == "short"
    assert res.trades[0].ret_pct > 0  # short gained as price fell


def test_no_trades_reports_buy_hold():
    n = 50
    df = _df([100.0] * n, [100.5] * n, [99.5] * n, list(range(100, 150)))

    def sig(df):
        return {"buy": False, "sell": False}

    res = run_backtest(df, sig, exits=ExitParams(), costs=CostModel(), warmup=35)
    assert res.n_trades == 0
    assert res.buy_hold_pct > 0  # price rose 100->149


def test_analyze_rule_based_without_llm():
    # build two fake results
    from backend.backtest.engine import BacktestResult
    a = BacktestResult(scenario="A", n_trades=10, total_return_pct=5, excess_vs_buy_hold=3,
                       profit_factor=2.0)
    b = BacktestResult(scenario="B", n_trades=10, total_return_pct=1, excess_vs_buy_hold=-2,
                       profit_factor=1.1)
    out = analyze_results([a, b], llm=None)
    assert out["available"] is False
    assert out["top_picks"][0] == "A"  # higher excess ranked first
