"""Append-only JSONL signal tape: one line per signal evaluation.

Lets us accumulate and later study signal quality before any capital is risked.
File rolls daily: logs/tape_YYYY-MM-DD.jsonl (UTC date).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..settings import REPO_DIR

LOG_DIR = REPO_DIR / "logs"


def _path_for(now: datetime) -> Path:
    return LOG_DIR / f"tape_{now.strftime('%Y-%m-%d')}.jsonl"


def append(event: dict) -> None:
    """Append one event as a JSON line to today's tape."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    event.setdefault("ts_utc", now.isoformat())
    with open(_path_for(now), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")
