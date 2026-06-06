"""Render backtest / walk-forward / committee results to Markdown, Word, or PDF.

``render_markdown(kind, data)`` is pure (no deps) and the single source of truth;
Word/PDF are produced from the same Markdown via lazy python-docx / reportlab.
``data`` may be a dict (the shape the web endpoints already return) or a dataclass
(converted with asdict) — accessors tolerate both.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..settings import REPO_DIR

REPORTS_DIR = REPO_DIR / "logs" / "reports"


def _as_dict(data) -> dict:
    if is_dataclass(data):
        return asdict(data)
    return dict(data) if data else {}


def _g(d: dict, key, default=""):
    v = d.get(key, default)
    return default if v is None else v


def render_markdown(kind: str, data) -> str:
    d = _as_dict(data)
    if kind == "backtest":
        return _md_backtest(d)
    if kind == "walkforward":
        return _md_walkforward(d)
    if kind == "committee":
        return _md_committee(d)
    raise ValueError(f"unknown report kind: {kind}")


def _md_backtest(d: dict) -> str:
    lines = [f"# Backtest Report — {_g(d, 'scenario') or _g(d, 'symbol')}", ""]
    rows = [("Trades", _g(d, "n_trades", 0)), ("Win rate %", _g(d, "win_rate")),
            ("Total return %", _g(d, "total_return_pct")),
            ("Buy & hold %", _g(d, "buy_hold_pct")),
            ("Excess vs B&H %", _g(d, "excess_vs_buy_hold")),
            ("Profit factor", _g(d, "profit_factor")), ("Sharpe", _g(d, "sharpe")),
            ("Max drawdown %", _g(d, "max_drawdown_pct")),
            ("p-value", _g(d, "p_value")), ("Significant", _g(d, "significant"))]
    lines += ["| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    if _g(d, "significance_label"):
        lines += ["", f"**Significance:** {_g(d, 'significance_label')}"]
    return "\n".join(lines) + "\n"


def _md_walkforward(d: dict) -> str:
    lines = [f"# Walk-Forward Report — {_g(d, 'symbol')} {_g(d, 'timeframe')}", ""]
    rows = [("Folds", _g(d, "n_folds", 0)), ("Avg IS return %", _g(d, "avg_is_return")),
            ("Avg OOS return %", _g(d, "avg_oos_return")),
            ("Avg OOS excess %", _g(d, "avg_oos_excess")),
            ("Degradation %", _g(d, "degradation_pct")),
            ("OOS positive folds", _g(d, "oos_positive_folds")),
            ("OOS beat B&H folds", _g(d, "oos_beat_bh_folds")),
            ("Verdict", _g(d, "verdict"))]
    lines += ["| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    folds = _g(d, "folds", []) or []
    if folds:
        lines += ["", "## Folds", "| Fold | Chosen | IS % | OOS % | OOS excess % | Trades |",
                  "|---|---|---|---|---|---|"]
        for f in folds:
            lines.append(f"| {_g(f,'fold')} | {_g(f,'chosen')} | {_g(f,'is_return_pct')} "
                         f"| {_g(f,'oos_return_pct')} | {_g(f,'oos_excess_pct')} "
                         f"| {_g(f,'oos_trades')} |")
    return "\n".join(lines) + "\n"


def _md_committee(d: dict) -> str:
    lines = [f"# Committee Analysis — {_g(d, 'symbol')}", "",
             f"**Decision:** {_g(d, 'side')} (confidence {_g(d, 'confidence')})", "",
             _g(d, "rationale"), ""]
    analysts = _g(d, "analyst_reports", []) or _g(d, "analysts", []) or []
    if analysts:
        lines += ["## Analyst Votes", "| Role | Side | Confidence | Rationale |",
                  "|---|---|---|---|"]
        for a in analysts:
            lines.append(f"| {_g(a,'role')} | {_g(a,'side')} | {_g(a,'confidence')} "
                         f"| {str(_g(a,'rationale')).replace('|','/')} |")
    if _g(d, "cost_usd"):
        lines += ["", f"_LLM cost: ${_g(d, 'cost_usd')}_"]
    return "\n".join(lines) + "\n"


def export_report(kind: str, data, fmt: str = "md", out_dir: Path | None = None):
    """Return (content_or_path, media_type, is_file).

    md  -> (markdown_text, 'text/markdown', False)
    docx-> (path, '...wordprocessingml...', True)   [needs python-docx]
    pdf -> (path, 'application/pdf', True)            [needs reportlab]
    """
    md = render_markdown(kind, data)
    if fmt == "md":
        return md, "text/markdown", False

    out_dir = out_dir or REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if fmt == "docx":
        path = out_dir / f"{kind}-{stamp}.docx"
        _md_to_docx(md, path)
        return path, ("application/vnd.openxmlformats-officedocument."
                      "wordprocessingml.document"), True
    if fmt == "pdf":
        path = out_dir / f"{kind}-{stamp}.pdf"
        _md_to_pdf(md, path)
        return path, "application/pdf", True
    raise ValueError(f"unknown report format: {fmt}")


def _md_to_docx(md: str, path: Path) -> None:
    from docx import Document  # lazy: optional python-docx

    doc = Document()
    for line in md.splitlines():
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("|"):
            doc.add_paragraph(line)  # simple monospace-ish row; tables kept as text
        elif line.strip():
            doc.add_paragraph(line)
    doc.save(str(path))


def _md_to_pdf(md: str, path: Path) -> None:
    from reportlab.lib.pagesizes import letter  # lazy: optional reportlab
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    flow = []
    for line in md.splitlines():
        if not line.strip():
            flow.append(Spacer(1, 6))
        elif line.startswith("# "):
            flow.append(Paragraph(line[2:], styles["Title"]))
        elif line.startswith("## "):
            flow.append(Paragraph(line[3:], styles["Heading2"]))
        else:
            flow.append(Paragraph(line.replace("<", "&lt;"), styles["Normal"]))
    SimpleDocTemplate(str(path), pagesize=letter).build(flow)
