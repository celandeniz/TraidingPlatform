"""Subprocess entry point for sandboxed candidate backtesting.

Run as: python -B -m backend.synthesis._worker  (stdin = JSON job, stdout = JSON result)

Applies resource limits, reconstructs the bar frame, runs the candidate via the
harness, and emits metrics as JSON. Any failure becomes {"ok": false, "detail"}.
This file is invoked by sandbox.py; it is never imported into the API process.
"""
from __future__ import annotations

import json
import sys


def _apply_limits(cpu_seconds: int, address_bytes: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        # No file writes (stdout is a pipe, unaffected by RLIMIT_FSIZE).
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        except (ValueError, OSError):
            pass
        # Address space cap is unreliable on macOS; best-effort only.
        if address_bytes:
            try:
                resource.setrlimit(resource.RLIMIT_AS, (address_bytes, address_bytes))
            except (ValueError, OSError):
                pass
    except Exception:  # noqa: BLE001 - resource missing (non-POSIX): rely on wall-clock
        pass


def _json_safe(o):
    """Coerce numpy scalars (bool_/int64/float64) to native JSON types."""
    if hasattr(o, "item"):
        try:
            return o.item()
        except Exception:  # noqa: BLE001
            pass
    return str(o)


def _frame(bars: dict):
    import pandas as pd

    idx = pd.to_datetime(bars["index"], utc=True)
    return pd.DataFrame(
        {k: bars[k] for k in ("open", "high", "low", "close", "volume")}, index=idx
    )


def main() -> None:
    raw = sys.stdin.read()
    try:
        job = json.loads(raw)
        _apply_limits(int(job.get("cpu_seconds", 10)),
                      int(job.get("address_bytes", 0)))
        from .harness import evaluate_candidate

        df = _frame(job["bars"])
        metrics = evaluate_candidate(
            job["source"], job["class_name"], df,
            config=job.get("config", {}), warmup=int(job.get("warmup", 35)),
        )
        print(json.dumps({"ok": True, "metrics": metrics}, default=_json_safe))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "detail": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    main()
