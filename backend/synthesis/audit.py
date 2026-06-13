"""Immutable JSONL audit trail for every synthesis run.

One line per run: brief, provider/model, every candidate's validation + metrics +
gate result, and the promotion decision. Mirrors the ledger/tournament store
conventions (backend/store/...). Provenance matters because the LLM factory can
silently fall back across providers.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..settings import REPO_DIR

AUDIT_DIR = REPO_DIR / "backend" / "store" / "synthesis"
AUDIT_PATH = AUDIT_DIR / "synthesis_audit.jsonl"


def record(event: dict, *, path: Path | str = AUDIT_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return p
