"""AI analysis of backtest results using the local models (analysis -> deepseek-r1).

Feeds a compact, factual summary of the grid to the LLM and asks it to (a) pick
the most ROBUST configs (not just highest return), (b) flag overfitting risks,
and (c) state honest caveats. The LLM never sees future data and cannot change
the numbers — it interprets them. Degrades to a pure-Python ranking if no LLM.
"""
from __future__ import annotations

from .engine import BacktestResult

_SYSTEM = (
    "You are a quantitative trading analyst. You are given REAL backtest results "
    "(no lookahead, costs included) WITH statistical significance (p-value, sample "
    "size n). Pick the most ROBUST configurations — favor STATISTICAL SIGNIFICANCE "
    "(low p-value, n>=20) and consistency (profit factor, low drawdown, positive "
    "excess vs buy-and-hold) over a single high return, which is likely overfit or "
    "noise. A high return with n<20 trades or p>0.05 is NOT trustworthy — say so. "
    "Be honest: if nothing is statistically significant, say it plainly. Not advice."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "description": "2-3 sentence honest read of the grid"},
        "top_picks": {"type": "array", "items": {"type": "string"},
                      "description": "scenario names you'd trust most, best first"},
        "overfitting_risk": {"type": "string", "description": "1-2 sentences"},
        "caveats": {"type": "string", "description": "honest limitations"},
    },
    "required": ["verdict", "top_picks", "overfitting_risk", "caveats"],
}


def _digest(results: list[BacktestResult], top_n: int = 15) -> str:
    traded = [r for r in results if r.n_trades > 0 and not r.error]
    profitable = sum(1 for r in traded if r.total_return_pct > 0)
    beat = sum(1 for r in traded if r.excess_vs_buy_hold > 0)
    sig_count = sum(1 for r in traded if getattr(r, "significant", False))
    lines = [
        f"{len(traded)} scenarios took trades. "
        f"{profitable} profitable net of costs, {beat} beat buy-and-hold, "
        f"{sig_count} STATISTICALLY SIGNIFICANT (p<0.05, n>=20).",
        "Top by excess-vs-buy-hold (name | trades | ret% | PF | excess | p | sig):",
    ]
    top = sorted(traded, key=lambda r: (r.excess_vs_buy_hold, r.profit_factor), reverse=True)[:top_n]
    for r in top:
        lines.append(f"{r.scenario} | n={r.n_trades} | {r.total_return_pct:.1f} | "
                     f"PF{r.profit_factor:.2f} | exc{r.excess_vs_buy_hold:.1f} | "
                     f"p={getattr(r, 'p_value', 1.0):.3f} | "
                     f"{'SIG' if getattr(r, 'significant', False) else 'noise'}")
    return "\n".join(lines)


def analyze_results(results: list[BacktestResult], llm=None) -> dict:
    """Return an AI (or rule-based) analysis of the grid.

    llm: an OllamaClient/ClaudeClient (structured()), or None -> pure-Python rank.
    """
    traded = [r for r in results if r.n_trades > 0 and not r.error]
    if not traded:
        return {"available": False, "verdict": "No scenarios produced trades."}

    if llm is None:
        ranked = sorted(traded, key=lambda r: (r.excess_vs_buy_hold, r.profit_factor),
                        reverse=True)[:5]
        return {
            "available": False,
            "verdict": "Rule-based ranking (no LLM). Picks favor excess-vs-buy-hold "
                       "then profit factor.",
            "top_picks": [r.scenario for r in ranked],
            "overfitting_risk": "Unassessed (LLM off).",
            "caveats": "Short history; intraday only; results are in-sample.",
        }

    try:
        out = llm.structured(
            system=_SYSTEM, user=_digest(results), tool_name="backtest_analysis",
            tool_schema=_SCHEMA, max_tokens=900, role="analysis",
        )
        out["available"] = True
        return out
    except Exception as exc:  # noqa: BLE001 - degrade to rule-based
        ranked = sorted(traded, key=lambda r: r.excess_vs_buy_hold, reverse=True)[:5]
        return {"available": False, "error": str(exc),
                "verdict": f"LLM analysis unavailable ({exc}); rule-based fallback.",
                "top_picks": [r.scenario for r in ranked]}
