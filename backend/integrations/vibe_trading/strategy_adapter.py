"""Vibe NL->strategy adapter (advisory / exploratory).

Like research, Vibe builds a strategy by running its agent loop inside a session:
send a natural-language strategy brief, the agent writes + backtests code, and the
result lands in a /runs/{run_id} record (with source under /runs/{run_id}/code).

This is DISJOINT from our own NL->strategy compiler in backend/synthesis/ (LLM ->
Python -> sandbox -> paper). Vibe output here is tagged source="vibe" and is
exploratory only: it is NEVER auto-promoted to paper. Auto-promotion belongs
exclusively to backend/synthesis/promoter.py.

Defensive throughout (Vibe's event/run schema is internal): unknown shapes degrade
to a summary-only result rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .research_adapter import _dig_id, _extract_text, _is_terminal

_RUN_KEYS = ("run_id", "runId", "run", "backtest_id", "backtestId")


@dataclass
class VibeStrategyResult:
    ok: bool
    prompt: str
    summary: str = ""
    run_id: str = ""
    metrics: dict = field(default_factory=dict)
    code_files: dict = field(default_factory=dict)
    session_id: str = ""
    events: int = 0
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "prompt": self.prompt, "summary": self.summary,
            "run_id": self.run_id, "metrics": self.metrics,
            "code_files": self.code_files, "session_id": self.session_id,
            "events": self.events, "detail": self.detail,
            "source": "vibe", "auto_promoted": False,
        }


def _dig_run_id(event: dict) -> str:
    for container in (event, event.get("data") or {}):
        if not isinstance(container, dict):
            continue
        for k in _RUN_KEYS:
            v = container.get(k)
            if v:
                return str(v)
    return ""


def build_strategy(client, prompt: str, *, max_events: int = 500,
                   fetch_code: bool = True) -> VibeStrategyResult:
    """Drive a Vibe session to build+backtest a strategy from `prompt`."""
    if not prompt or not prompt.strip():
        return VibeStrategyResult(False, prompt, detail="empty prompt")

    sess = client.create_session(title="strategy")
    if not sess.get("ok", False):
        return VibeStrategyResult(False, prompt, detail=sess.get("detail", "session failed"))
    session_id = _dig_id(sess)
    if not session_id:
        return VibeStrategyResult(False, prompt, detail="no session id in response")

    sent = client.send_message(session_id, prompt)
    if not sent.get("ok", False):
        return VibeStrategyResult(False, prompt, session_id=session_id,
                                  detail=sent.get("detail", "send failed"))

    chunks: list[str] = []
    run_id = ""
    count = 0
    for event in client.session_events(session_id):
        count += 1
        if not isinstance(event, dict):
            continue
        if event.get("ok") is False:
            break
        text = _extract_text(event)
        if text:
            chunks.append(text)
        run_id = run_id or _dig_run_id(event)
        if _is_terminal(event) or count >= max_events:
            break

    summary = chunks[-1] if chunks else ""
    metrics: dict = {}
    code_files: dict = {}
    if run_id:
        run = client.get_run(run_id)
        if run.get("ok", True):
            data = run.get("data") if isinstance(run.get("data"), dict) else run
            metrics = data.get("metrics", {}) if isinstance(data, dict) else {}
        if fetch_code:
            code = client.get_run_code(run_id)
            if isinstance(code.get("data"), dict):
                code_files = code["data"]
            elif code.get("ok") and isinstance(code, dict):
                code_files = {k: v for k, v in code.items()
                              if k not in ("ok", "detail") and isinstance(v, str)}

    ok = bool(summary or run_id)
    return VibeStrategyResult(
        ok=ok, prompt=prompt, summary=summary, run_id=run_id, metrics=metrics,
        code_files=code_files, session_id=session_id, events=count,
        detail="" if ok else "no strategy output produced",
    )
