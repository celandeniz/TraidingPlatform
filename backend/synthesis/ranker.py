"""Rank candidate backtests using the EXISTING tournament risk gates.

We do not reinvent gating: build a StrategyReport per candidate and defer to
tournament.apply_gates / rank_reports. Passing reports come first, ordered by
metrics["oos_sharpe"] (overfit guard), exactly like the strategy tournament.
"""
from __future__ import annotations

from ..backtest.tournament import StrategyReport, apply_gates, rank_reports


def to_report(name: str, metrics: dict) -> StrategyReport:
    error = metrics.get("error", "") if isinstance(metrics, dict) else ""
    return StrategyReport(name=name, kind="trades", metrics=metrics or {}, error=error)


def rank(named_metrics: list[tuple[str, dict]]) -> list[StrategyReport]:
    """named_metrics: [(name, metrics_dict), ...] -> ranked StrategyReports
    (each with .gates attached by rank_reports)."""
    reports = [to_report(name, m) for name, m in named_metrics]
    return rank_reports(reports)


def passing(reports: list[StrategyReport]) -> list[StrategyReport]:
    return [r for r in reports if r.gates and r.gates.get("passed")]
