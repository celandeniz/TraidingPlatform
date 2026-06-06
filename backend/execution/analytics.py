"""Execution analytics — measure how good (or bad) each fill actually was.

The institutional-desk question for an automated transaction isn't just "did it
fill?" but "how much did we pay vs. the price when we decided?" This records, per
executed order, the **arrival price** (mid/decision price), the realized **fill
price**, and the resulting **slippage in bps** (implementation shortfall). Results
append to logs/exec_analytics.jsonl and are summarizable for a desk-style report.

Clean-room; standard transaction-cost-analysis (TCA) concept.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..settings import REPO_DIR
from .base import OrderResult

ANALYTICS_PATH = REPO_DIR / "logs" / "exec_analytics.jsonl"


@dataclass
class ExecReport:
    order_id: Optional[str]
    symbol: str
    side: str
    requested_qty: float
    filled_qty: float
    arrival_price: float       # mid/decision price when the order was created
    fill_price: float          # average realized fill
    slippage_bps: float        # signed adverse cost vs arrival (>0 = paid up / sold cheap)
    fill_ratio: float          # filled_qty / requested_qty
    status: str
    ts_utc: str = ""


def slippage_bps(arrival: float, fill: float, side: str) -> float:
    """Adverse slippage in bps. Positive = worse than arrival for the trader:
    a buy that filled above arrival, or a sell that filled below it."""
    if arrival <= 0 or fill <= 0:
        return 0.0
    raw = (fill / arrival - 1.0) * 10000.0
    return raw if side == "buy" else -raw


class ExecutionAnalytics:
    def __init__(self, path: Optional[Path] = None, clock=None):
        self._path = path or ANALYTICS_PATH
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def record(self, result: OrderResult, arrival_price: float) -> ExecReport:
        filled = result.filled_qty if result.filled_qty is not None else result.qty
        fill_px = result.fill_price if result.fill_price is not None else arrival_price
        rep = ExecReport(
            order_id=result.order_id, symbol=result.symbol, side=result.side,
            requested_qty=result.qty, filled_qty=filled,
            arrival_price=arrival_price, fill_price=fill_px,
            slippage_bps=round(slippage_bps(arrival_price, fill_px, result.side), 4),
            fill_ratio=round(filled / result.qty, 4) if result.qty else 0.0,
            status=result.status, ts_utc=self._clock().isoformat(),
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rep), default=str) + "\n")
        return rep

    def summary(self) -> dict:
        """Aggregate TCA across recorded fills: count, avg/median slippage, fill rate."""
        reps = self._read()
        if not reps:
            return {"n": 0, "avg_slippage_bps": 0.0, "avg_fill_ratio": 0.0}
        slips = sorted(r["slippage_bps"] for r in reps)
        n = len(slips)
        return {
            "n": n,
            "avg_slippage_bps": round(sum(slips) / n, 4),
            "median_slippage_bps": slips[n // 2],
            "worst_slippage_bps": slips[-1],
            "avg_fill_ratio": round(sum(r["fill_ratio"] for r in reps) / n, 4),
        }

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
        return out
