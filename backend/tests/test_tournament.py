"""Tournament: gates, ranking, error isolation, persistence."""
import json
import math

import pandas as pd
import pytest

from backend.backtest.tournament import (
    GATES, StrategyReport, apply_gates, rank_reports, run_tournament, save_run,
    load_latest, list_runs, _trade_metrics,
)


def _report(name, *, sharpe=1.0, max_dd=10.0, pf=2.0, trades=200,
            kind="trades", significant=True, error=""):
    return StrategyReport(
        name=name, kind=kind, error=error,
        metrics={"oos_sharpe": sharpe, "max_drawdown_pct": max_dd,
                 "profit_factor": pf, "n_trades": trades,
                 "n_rebalances": trades, "significant": significant,
                 "total_return_pct": 10.0},
    )


def test_gates_pass_and_fail_reasons():
    ok = apply_gates(_report("good"))
    assert ok.passed and ok.failures == []
    bad = apply_gates(_report("dd", max_dd=35.0, pf=1.1, trades=5))
    assert not bad.passed
    assert any("drawdown" in f for f in bad.failures)
    assert any("profit factor" in f for f in bad.failures)
    assert any("trades" in f for f in bad.failures)


def test_portfolio_kind_uses_rebalance_gate():
    r = _report("port", kind="portfolio", trades=30)
    r.metrics["n_trades"] = 0
    r.metrics["n_rebalances"] = 30
    assert apply_gates(r).passed


def test_rank_orders_by_sharpe_passers_first():
    reports = [_report("a", sharpe=0.5), _report("b", sharpe=2.0),
               _report("c", max_dd=50.0), _report("err", error="boom")]
    ranked = rank_reports(reports)
    names = [r.name for r in ranked]
    assert names[:2] == ["b", "a"]          # passers by sharpe desc
    assert set(names[2:]) == {"c", "err"}   # failures after, never hidden


def test_run_tournament_isolates_strategy_errors():
    def good(config):
        return _report("good")

    def boom(config):
        raise RuntimeError("data exploded")

    run = run_tournament({}, runners={"good": good, "boom": boom})
    by_name = {r.name: r for r in run.reports}
    assert by_name["good"].error == ""
    assert "data exploded" in by_name["boom"].error
    assert run.ranked[0].name == "good"


def test_save_and_load_roundtrip(tmp_path):
    run = run_tournament({}, runners={"good": lambda c: _report("good")})
    path = save_run(run, store_dir=tmp_path)
    assert path.exists()
    latest = load_latest(store_dir=tmp_path)
    assert latest["reports"][0]["name"] == "good"
    assert list_runs(store_dir=tmp_path)[0]["file"] == path.name


# ------------------------------------------------------------------ new tests
# C1: annualised cross-kind Sharpe
def test_trade_metrics_annualizes_sharpe():
    # 100 identical-ish winning trades over ~1 year of trading days
    ts = list(pd.bdate_range("2025-01-02", periods=100))
    trades = [(t, 0.5 + (i % 3) * 0.1) for i, t in enumerate(ts)]
    m = _trade_metrics(trades, span_days=252.0)
    assert m["n_trades"] == 100
    assert m["per_trade_sharpe"] > 0
    # trades_per_year = 100 * 252 / 252 = 100  -> annualized = per_trade * sqrt(100) = per_trade * 10
    assert m["oos_sharpe"] == pytest.approx(m["per_trade_sharpe"] * 10.0, rel=1e-6)


# I1: drawdown computed in chronological order, not input order
def test_trade_metrics_drawdown_is_chronological():
    early = pd.Timestamp("2025-01-05")
    late = pd.Timestamp("2025-06-05")
    # losses happen FIRST chronologically; passed INTERLEAVED so input-order
    # compounding gives a different DD than chronological compounding
    trades = [(late, +10.0), (early, -5.0), (late, +10.0), (early, -5.0)]
    m = _trade_metrics(trades, span_days=252.0)
    # Chronological order: -5, -5, +10, +10
    # equity: 1 -> 0.95 -> 0.9025 (max DD 9.75%) -> 0.99275 -> 1.092
    # Input order (+10, -5, +10, -5) would give only a 5.0% DD — the sort matters.
    assert m["max_drawdown_pct"] == pytest.approx(9.75, abs=0.1)


# Mixed-kind ranking uses a single annualised scale
def test_mixed_kind_ranking_is_on_one_scale():
    port = _report("port", kind="portfolio", sharpe=1.2)
    trade = _report("trade", kind="trades", sharpe=3.0)
    ranked = rank_reports([port, trade])
    assert [r.name for r in ranked][:2] == ["trade", "port"]
