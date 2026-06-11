"""Tournament: gates, ranking, error isolation, persistence."""
import json

import pandas as pd
import pytest

from backend.backtest.tournament import (
    GATES, StrategyReport, apply_gates, rank_reports, run_tournament, save_run,
    load_latest, list_runs,
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
