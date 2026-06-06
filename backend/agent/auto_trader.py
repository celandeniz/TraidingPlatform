"""AutoTrader — guard-protected autonomous action loop.

One ``run_cycle()`` gathers live context (positions, account, recent signals, and
optionally news), asks a provider-agnostic LLM for structured actions, then for
each proposed action applies hard safety filters and EITHER records it (dry-run)
or submits it through the Toolset — which routes via the OMS + guard pipeline +
RiskManager, exactly like a human order. Every cycle is appended to
logs/auto_trader.jsonl for audit.

Safety posture (defense in depth):
  * dry_run defaults True — proposes, does not trade, until explicitly disabled.
  * symbol_whitelist, min_confidence, max_actions_per_cycle, max_qty caps.
  * execution still passes the guard pipeline + risk + kill-switch downstream.
  * "hold" / unknown actions are ignored; reduce_only closes are always allowed.

Clean-room; the LLM is whatever llm_factory builds (Ollama/Claude/Gemini).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..settings import REPO_DIR

AUTO_LOG_PATH = REPO_DIR / "logs" / "auto_trader.jsonl"

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                    "qty": {"type": "number"},
                    "reduce_only": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["symbol", "action"],
            },
        }
    },
    "required": ["actions"],
}

_SYSTEM = (
    "You are a disciplined trading assistant. Given the account context, propose a "
    "SHORT list of concrete actions (buy/sell/hold) with a qty, a confidence in "
    "[0,1], and a one-line reason. Only act when there is a clear edge; prefer "
    "'hold'. You are NOT the final authority — every action passes risk guards and "
    "may be dry-run. Return JSON matching the schema."
)


class AutoTrader:
    def __init__(self, toolset, llm, cfg: dict, *, news=None, clock=None,
                 store_path: Optional[Path] = None):
        self._ts = toolset            # backend.mcp.tools.Toolset
        self._llm = llm               # structured()-capable client (or None)
        self._cfg = cfg or {}
        self._news = news             # UnifiedNews | None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._path = store_path or AUTO_LOG_PATH

    # --- context -----------------------------------------------------------
    def build_context(self) -> dict:
        ctx = {"positions": self._ts.list_positions().get("positions", []),
               "account": self._ts.account_summary().get("account", {}),
               "recent_signals": self._ts.recent_signals(limit=10).get("signals", [])}
        if self._news is not None and self._cfg.get("include_news"):
            syms = {p.get("symbol") for p in ctx["positions"]}
            heads = []
            for s in list(syms)[:3]:
                heads += [{"symbol": h.symbol, "headline": h.headline}
                          for h in self._news.latest(symbol=s, limit=3)]
            ctx["news"] = heads
        return ctx

    # --- decision ----------------------------------------------------------
    def decide(self, context: dict) -> list[dict]:
        if self._llm is None:
            return []
        try:
            out = self._llm.structured(
                system=_SYSTEM, user=json.dumps(context, default=str),
                tool_name="actions", tool_schema=DECISION_SCHEMA, max_tokens=800,
                use_case="reasoning")
        except Exception:  # noqa: BLE001 - LLM unavailable -> propose nothing
            return []
        return out.get("actions", []) if isinstance(out, dict) else []

    # --- cycle -------------------------------------------------------------
    def run_cycle(self, seed_candidates: Optional[list] = None) -> dict:
        if not self._cfg.get("enabled"):
            return {"ran": False, "detail": "auto_trader disabled"}
        context = self.build_context()
        if seed_candidates:
            # Scanner-ranked buy candidates (estimated edge, not a guarantee) the LLM
            # should consider this cycle, alongside positions/signals/news.
            context["scanner_candidates"] = seed_candidates[:15]
        proposed = self.decide(context)
        dry_run = self._cfg.get("dry_run", True)
        whitelist = {s.upper() for s in (self._cfg.get("symbol_whitelist") or [])}
        min_conf = float(self._cfg.get("min_confidence", 0.6))
        max_actions = int(self._cfg.get("max_actions_per_cycle", 3))
        max_qty = float(self._cfg.get("max_qty", 10))

        results = []
        for a in proposed:
            decision = self._evaluate_action(a, whitelist, min_conf, max_qty)
            if decision.get("status") == "skipped":
                results.append(decision)
                continue
            if len([r for r in results if r["status"] in ("proposed", "executed")]) >= max_actions:
                decision["status"] = "skipped"
                decision["detail"] = "max_actions_per_cycle reached"
                results.append(decision)
                continue
            if dry_run:
                decision["status"] = "proposed"
            else:
                res = self._ts.submit_order(
                    decision["symbol"], decision["action"], decision["qty"],
                    reduce_only=decision.get("reduce_only", False),
                    message=f"auto: {decision.get('reason', '')}"[:120])
                decision["status"] = "executed" if res.get("ok") else "rejected"
                decision["result"] = res
            results.append(decision)

        record = {"ts_utc": self._clock().isoformat(), "dry_run": dry_run,
                  "n_proposed": len(proposed), "actions": results}
        self._log(record)
        return {"ran": True, **record}

    def _evaluate_action(self, a: dict, whitelist: set, min_conf: float,
                         max_qty: float) -> dict:
        symbol = str(a.get("symbol", "")).upper()
        action = str(a.get("action", "hold")).lower()
        qty = min(float(a.get("qty", 0) or 0), max_qty)
        conf = float(a.get("confidence", 0) or 0)
        base = {"symbol": symbol, "action": action, "qty": qty,
                "confidence": conf, "reason": a.get("reason", ""),
                "reduce_only": bool(a.get("reduce_only", False))}

        def skip(why):
            return {**base, "status": "skipped", "detail": why}

        if action not in ("buy", "sell"):
            return skip("not an actionable side")
        if not symbol:
            return skip("missing symbol")
        if whitelist and symbol not in whitelist:
            return skip(f"{symbol} not in whitelist")
        if conf < min_conf:
            return skip(f"confidence {conf:.2f} < {min_conf:.2f}")
        if qty <= 0:
            return skip("qty <= 0")
        return base  # eligible (status set by caller)

    def _log(self, record: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
