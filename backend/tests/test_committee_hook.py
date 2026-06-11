"""Committee hook: extra_reports seam; panel report mapping."""
from __future__ import annotations

import pytest

from backend.research.base import AnalystReport
from backend.research.panel import PanelResult
from backend.web.app import _panel_report


def test_panel_report_maps_verdict_and_score():
    res = PanelResult(symbol="AAPL", verdict="long", score=0.42, votes=[],
                      fundamentals_available=True, generated_at="t")
    rep = _panel_report(res)
    assert isinstance(rep, AnalystReport)
    assert rep.role == "persona_panel"
    assert rep.side == "long"
    assert rep.confidence == 0.42
    assert rep.available is True


def test_panel_report_short_uses_abs_score():
    res = PanelResult(symbol="AAPL", verdict="short", score=-0.3, votes=[],
                      fundamentals_available=False, generated_at="t")
    rep = _panel_report(res)
    assert rep.side == "short"
    assert rep.confidence == pytest.approx(0.3)   # abs(score)
    assert rep.available is True


def test_run_committee_accepts_extra_reports(monkeypatch):
    """extra_reports flow into the analyst stage; default None unchanged."""
    import backend.research.agents.committee as committee_mod

    captured = {}

    def fake_run_analysts(client, symbol, **kw):
        return [AnalystReport(role="value", side="pass", confidence=0.1,
                              rationale="r")]

    def fake_summarize(reports):
        captured["roles"] = [r.role for r in reports]
        raise RuntimeError("stop early — only the analyst stage matters here")

    monkeypatch.setattr(committee_mod, "run_analysts", fake_run_analysts)
    monkeypatch.setattr(committee_mod, "summarize_reports", fake_summarize)

    extra = AnalystReport(role="persona_panel", side="long", confidence=0.4,
                          rationale="panel")

    # run_committee wraps ALL exceptions via `except Exception`, so the
    # RuntimeError from fake_summarize is swallowed and a degraded
    # CommitteeVerdict (available=False) is returned — not re-raised.
    # We just check that captured["roles"] was set before the exception.
    class _C:
        spent_usd = 0.0

    result = committee_mod.run_committee(
        _C(), "AAPL", "buy", context="c", headlines=[], gate=_gate(),
        bb_meta={}, cfg={}, extra_reports=[extra],
    )
    # The RuntimeError is swallowed; captured["roles"] must have been set
    assert captured["roles"] == ["value", "persona_panel"]
    # Also confirm it degraded rather than crashed the test
    assert result.available is False


def _gate():
    from backend.research.base import CatalystVerdict
    # GateVerdict literal must be "ALLOW" (uppercase) — per base.py
    return CatalystVerdict(verdict="ALLOW")
