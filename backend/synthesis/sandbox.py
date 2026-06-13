"""Run a validated candidate in an isolated subprocess.

A fresh `python -B -m backend.synthesis._worker` per candidate, with:
  * resource rlimits (CPU time, no file writes, best-effort address space)
  * a scrubbed environment (no API keys / network credentials)
  * a parent-side wall-clock timeout that kills the child on overrun

A crash, timeout, or non-zero exit degrades to {"ok": false, "detail"} — the
candidate fails, the platform is unaffected. This is the hard safety boundary;
validator.py is the cheap pre-filter in front of it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Optional

# Only the variables the worker legitimately needs. No ALPACA_*/ANTHROPIC_*/etc.
_SAFE_ENV = ("PATH", "PYTHONPATH", "HOME", "LANG", "LC_ALL", "TMPDIR")


def _serialize(df) -> dict:
    return {
        "index": [t.isoformat() for t in df.index],
        "open": df["open"].tolist(), "high": df["high"].tolist(),
        "low": df["low"].tolist(), "close": df["close"].tolist(),
        "volume": df["volume"].tolist(),
    }


def run_candidate(source: str, class_name: str, df, *, config: Optional[dict] = None,
                  warmup: int = 35, cpu_seconds: int = 10, wall_seconds: int = 20,
                  address_mb: int = 1024) -> dict:
    """Backtest one candidate in a sandboxed subprocess; return its metrics dict."""
    import os

    job = {
        "source": source, "class_name": class_name, "bars": _serialize(df),
        "config": config or {}, "warmup": warmup,
        "cpu_seconds": cpu_seconds, "address_bytes": address_mb * 1024 * 1024,
    }
    env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "backend.synthesis._worker"],
            input=json.dumps(job), capture_output=True, text=True,
            timeout=wall_seconds, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"timeout after {wall_seconds}s (killed)"}
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-300:]
        return {"ok": False, "detail": f"worker exit {proc.returncode}: {tail}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "detail": "unparseable worker output"}
