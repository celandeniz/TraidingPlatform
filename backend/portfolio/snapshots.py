"""Account snapshots + equity curve.

Periodic or event-driven capture of account equity/cash/positions to an
append-only JSONL log (logs/snapshots_YYYY-MM-DD.jsonl), and a reader that
returns the equity curve for charting. Clean-room reimplementation of the
OpenAlice snapshot concept.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..execution.base import ExecutionAdapter
from ..settings import REPO_DIR

SNAPSHOT_DIR = REPO_DIR / "logs"


class SnapshotStore:
    def __init__(self, directory: Optional[Path] = None, clock=None):
        self._dir = directory or SNAPSHOT_DIR
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _path_for(self, now: datetime) -> Path:
        return self._dir / f"snapshots_{now.strftime('%Y-%m-%d')}.jsonl"

    def capture(self, executor: ExecutionAdapter, reason: str = "periodic") -> dict:
        """Snapshot the account now and append it to today's log."""
        now = self._clock()
        try:
            account = executor.account_summary()
        except Exception as exc:  # noqa: BLE001
            account = {"status": "error", "detail": str(exc), "equity": 0.0, "cash": 0.0}
        try:
            positions = executor.list_positions()
        except Exception:  # noqa: BLE001
            positions = []
        snap = {
            "ts_utc": now.isoformat(),
            "reason": reason,
            "equity": float(account.get("equity", 0) or 0),
            "cash": float(account.get("cash", 0) or 0),
            "open_positions": len(positions),
            "positions": positions,
            "account": account,
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._path_for(now), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap, default=str) + "\n")
        return snap

    def equity_curve(self, days: int = 7) -> list[dict]:
        """Return [{ts_utc, equity, cash}] across the most recent ``days`` logs."""
        files = sorted(self._dir.glob("snapshots_*.jsonl"))[-days:]
        out: list[dict] = []
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        s = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    out.append({"ts_utc": s.get("ts_utc"), "equity": s.get("equity"),
                                "cash": s.get("cash")})
        return out
