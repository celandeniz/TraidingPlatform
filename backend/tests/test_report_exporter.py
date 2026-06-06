"""Report exporter tests — Markdown is pure; docx/pdf import-guarded."""
import importlib

import pytest

from backend.report.exporter import export_report, render_markdown

BT = {"scenario": "MSFT|5m|spike_fade", "symbol": "MSFT", "n_trades": 30,
      "win_rate": 53.3, "total_return_pct": 4.2, "buy_hold_pct": 1.1,
      "excess_vs_buy_hold": 3.1, "profit_factor": 1.6, "sharpe": 0.4,
      "max_drawdown_pct": 2.8, "p_value": 0.03, "significant": True,
      "significance_label": "significant (p<0.05)"}

WF = {"symbol": "AAPL", "timeframe": "5m", "n_folds": 4, "avg_is_return": 2.0,
      "avg_oos_return": 0.8, "avg_oos_excess": 0.3, "degradation_pct": 1.2,
      "oos_positive_folds": 3, "oos_beat_bh_folds": 2, "verdict": "robust-ish",
      "folds": [{"fold": 1, "chosen": "sf_z2_k2", "is_return_pct": 2.1,
                 "oos_return_pct": 0.9, "oos_excess_pct": 0.4, "oos_trades": 12}]}

COMMITTEE = {"symbol": "TSLA", "side": "long", "confidence": 0.7, "rationale": "edge",
             "cost_usd": 0.012,
             "analyst_reports": [{"role": "sentiment_news", "side": "long",
                                  "confidence": 0.7, "rationale": "bullish | tone"}]}


def test_backtest_markdown():
    md = render_markdown("backtest", BT)
    assert md.startswith("# Backtest Report — MSFT|5m|spike_fade")
    assert "Total return %" in md and "| Significant | True |" in md


def test_walkforward_markdown_with_folds():
    md = render_markdown("walkforward", WF)
    assert "Walk-Forward Report — AAPL 5m" in md
    assert "## Folds" in md and "sf_z2_k2" in md


def test_committee_markdown_escapes_pipe():
    md = render_markdown("committee", COMMITTEE)
    assert "Committee Analysis — TSLA" in md
    assert "sentiment_news" in md
    assert "bullish / tone" in md  # pipe in rationale replaced so table stays valid


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        render_markdown("nope", {})


def test_export_md_returns_text():
    content, media, is_file = export_report("backtest", BT, "md")
    assert is_file is False and media == "text/markdown"
    assert content.startswith("# Backtest Report")


@pytest.mark.skipif(importlib.util.find_spec("docx") is None, reason="python-docx not installed")
def test_export_docx_writes_file(tmp_path):
    path, media, is_file = export_report("backtest", BT, "docx", out_dir=tmp_path)
    assert is_file and path.exists() and path.suffix == ".docx"


@pytest.mark.skipif(importlib.util.find_spec("reportlab") is None, reason="reportlab not installed")
def test_export_pdf_writes_file(tmp_path):
    path, media, is_file = export_report("walkforward", WF, "pdf", out_dir=tmp_path)
    assert is_file and path.exists() and path.suffix == ".pdf"
