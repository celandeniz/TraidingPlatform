"""Reflection-memory — learn from closed trades, feed lessons forward.

When a position closes, optionally ask the LLM to reflect ("what worked / what
failed?") and store a short, durable lesson keyed by symbol + exit reason. Past
lessons can then be surfaced into future decision/committee context so the system
doesn't repeat the same mistakes. Inspired by TradingAgents' reflection layer;
clean-room Python.

Storage: append-only logs/reflections.jsonl. Fully optional (reflection.enabled),
best-effort, and never raises into the trading path.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..settings import REPO_DIR

REFLECTIONS_PATH = REPO_DIR / "logs" / "reflections.jsonl"

_LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "tag": {"type": "string", "enum": ["win", "loss", "neutral"]},
        "lesson": {"type": "string", "description": "<=1 sentence, actionable"},
    },
    "required": ["tag", "lesson"],
}

_SYSTEM = (
    "You review a single closed trade and extract ONE short, actionable lesson "
    "for future trades on similar setups. Be concrete and unsentimental. "
    "Not investment advice."
)


@dataclass
class TradeClosure:
    symbol: str
    side: str                 # "long" | "short"
    entry: float
    exit: float
    ret_pct: float            # signed, net for the position
    opened_at: str
    closed_at: str
    exit_reason: str
    regime: str = ""
    rationale: str = ""       # the original decision rationale, if known


class ReflectionMemory:
    def __init__(self, *, path: Optional[Path] = None, llm=None, use_llm: bool = True,
                 max_notes: int = 200, clock=None):
        self._path = path or REFLECTIONS_PATH
        self._llm = llm
        self._use_llm = use_llm
        self._max_notes = max_notes
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def record_closure(self, closure: TradeClosure) -> dict:
        """Reflect on a closed trade and persist a lesson. Never raises."""
        tag, lesson = self._reflect(closure)
        note = {**asdict(closure), "tag": tag, "lesson": lesson,
                "ts_utc": self._clock().isoformat()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(note, default=str) + "\n")
        except Exception:  # noqa: BLE001 - logging a lesson must never break trading
            pass
        return note

    def _reflect(self, c: TradeClosure) -> tuple:
        heuristic_tag = "win" if c.ret_pct > 0 else ("loss" if c.ret_pct < 0 else "neutral")
        if not (self._use_llm and self._llm is not None):
            return heuristic_tag, f"{c.exit_reason}: {heuristic_tag} {c.ret_pct:+.2f}%"
        try:
            out = self._llm.structured(
                system=_SYSTEM,
                user=(f"Symbol {c.symbol} {c.side}; entry {c.entry} exit {c.exit} "
                      f"return {c.ret_pct:+.2f}%; exit_reason {c.exit_reason}; "
                      f"regime {c.regime}; original thesis: {c.rationale or 'n/a'}."),
                tool_name="lesson", tool_schema=_LESSON_SCHEMA, max_tokens=180,
                use_case="fast")
            return str(out.get("tag", heuristic_tag)), str(out.get("lesson", ""))[:240]
        except Exception:  # noqa: BLE001 - LLM down -> heuristic lesson
            return heuristic_tag, f"{c.exit_reason}: {heuristic_tag} {c.ret_pct:+.2f}%"

    def recent(self, symbol: Optional[str] = None, regime: Optional[str] = None,
               limit: int = 10) -> list[dict]:
        notes = self._read()
        if symbol:
            notes = [n for n in notes if n.get("symbol", "").upper() == symbol.upper()]
        if regime:
            notes = [n for n in notes if n.get("regime") == regime]
        return notes[-limit:]

    def notes_text(self, symbol: Optional[str] = None, limit: int = 5) -> str:
        """Compact lesson digest for injecting into LLM decision/committee context."""
        notes = self.recent(symbol=symbol, limit=limit)
        if not notes:
            return ""
        return "Past lessons:\n" + "\n".join(
            f"- [{n.get('tag')}] {n.get('symbol')} {n.get('exit_reason')}: {n.get('lesson')}"
            for n in notes)

    def _read(self) -> list[dict]:
        if not self._path.exists():
            return []
        out = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out[-self._max_notes:]
