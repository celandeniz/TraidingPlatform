"""Report export — backtest / walk-forward / committee results to MD/Word/PDF.

Markdown rendering is pure stdlib (always available); Word (python-docx) and PDF
(reportlab) are lazy/optional. Clean-room reimplementation of the report-export
idea from TradingAgents-CN (no CN code).
"""
from .exporter import export_report, render_markdown

__all__ = ["render_markdown", "export_report"]
