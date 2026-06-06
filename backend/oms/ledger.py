"""OrderManager — staged -> committed -> pushed order lifecycle ("Trading-as-Git").

Every order moves through explicit states, and every transition is appended to an
append-only JSONL ledger (logs/order_ledger.jsonl) so the full history is auditable
and reviewable by id — the order-flow analogue of git stage/commit/push:

    stage(req, note)      -> "staged"     (intent recorded; nothing sent)
    commit(id, message)   -> "committed"  (reviewed + annotated; still not sent)
    push(id)              -> "pushed" then "filled"/"rejected" (adapter.submit runs)
    discard(id)           -> "discarded"  (abandon a staged/committed order)

In-memory state is rebuilt by replaying the ledger on construction, so history
survives restarts. push() is the ONLY thing that calls the ExecutionAdapter, so
guards/risk wrapping the adapter still apply unchanged.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..execution.base import ExecutionAdapter, OrderRequest, OrderResult
from ..settings import REPO_DIR

LEDGER_PATH = REPO_DIR / "logs" / "order_ledger.jsonl"

# Allowed forward transitions; push has two outcomes recorded separately.
_OPEN_STATES = {"staged", "committed"}


@dataclass
class OrderRecord:
    id: str
    state: str                      # staged | committed | pushed | filled | rejected | discarded
    request: dict                   # serialized OrderRequest
    note: str = ""
    message: str = ""               # commit message
    result: Optional[dict] = None   # serialized OrderResult after push
    history: list = field(default_factory=list)  # [{ts_utc, state, detail}]


class OrderManager:
    def __init__(self, adapter: ExecutionAdapter, *, ledger_path: Optional[Path] = None,
                 clock=None, analytics=None):
        self._adapter = adapter
        self._path = ledger_path or LEDGER_PATH
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._analytics = analytics  # ExecutionAnalytics | None — records TCA per push
        self._orders: dict[str, OrderRecord] = {}
        self._replay()

    # --- persistence -------------------------------------------------------
    def _replay(self) -> None:
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply(rec, persist=False)

    def _emit(self, oid: str, state: str, detail: str = "", **extra) -> None:
        entry = {"id": oid, "state": state, "ts_utc": self._clock().isoformat(),
                 "detail": detail, **extra}
        self._apply(entry, persist=True)

    def _apply(self, entry: dict, *, persist: bool) -> None:
        oid = entry["id"]
        state = entry["state"]
        rec = self._orders.get(oid)
        if rec is None:
            rec = OrderRecord(id=oid, state=state, request=entry.get("request", {}))
            self._orders[oid] = rec
        rec.state = state
        if "request" in entry:
            rec.request = entry["request"]
        if "note" in entry:
            rec.note = entry["note"]
        if "message" in entry:
            rec.message = entry["message"]
        if "result" in entry:
            rec.result = entry["result"]
        rec.history.append({"ts_utc": entry.get("ts_utc"), "state": state,
                             "detail": entry.get("detail", "")})
        if persist:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")

    # --- lifecycle ---------------------------------------------------------
    def stage(self, req: OrderRequest, note: str = "") -> str:
        oid = uuid.uuid4().hex[:12]
        self._emit(oid, "staged", detail=note, request=asdict(req), note=note)
        return oid

    def commit(self, order_id: str, message: str) -> OrderRecord:
        rec = self._require(order_id, {"staged"})
        self._emit(order_id, "committed", detail=message, message=message)
        return self._orders[order_id]

    def push(self, order_id: str) -> OrderResult:
        rec = self._require(order_id, {"committed"})
        req = _request_from_dict(rec.request)
        self._emit(order_id, "pushed")
        result = self._adapter.submit(req)
        final = "filled" if result.ok else "rejected"
        self._emit(order_id, final, detail=result.detail, result=asdict(result))
        # Transaction-cost analysis: record realized slippage vs the arrival price
        # (decision price). Best-available arrival: explicit meta, limit, else fill.
        if self._analytics is not None and result.ok:
            arrival = (req.meta.get("arrival") or req.meta.get("price")
                       or req.limit_price or result.fill_price or 0.0)
            if arrival:
                self._analytics.record(result, float(arrival))
        return result

    def discard(self, order_id: str, reason: str = "") -> None:
        self._require(order_id, _OPEN_STATES)
        self._emit(order_id, "discarded", detail=reason)

    def stage_commit_push(self, req: OrderRequest, message: str, note: str = "") -> OrderResult:
        """Convenience: the full flow in one call (auto-approved orders)."""
        oid = self.stage(req, note=note)
        self.commit(oid, message)
        return self.push(oid)

    # --- queries -----------------------------------------------------------
    def get(self, order_id: str) -> Optional[OrderRecord]:
        return self._orders.get(order_id)

    def open_orders(self) -> list[OrderRecord]:
        return [r for r in self._orders.values() if r.state in _OPEN_STATES]

    def history(self) -> list[OrderRecord]:
        return list(self._orders.values())

    def _require(self, order_id: str, allowed: set[str]) -> OrderRecord:
        rec = self._orders.get(order_id)
        if rec is None:
            raise KeyError(f"unknown order {order_id}")
        if rec.state not in allowed:
            raise ValueError(f"order {order_id} is '{rec.state}', expected one of {sorted(allowed)}")
        return rec


def _request_from_dict(d: dict) -> OrderRequest:
    fields = {"symbol", "side", "qty", "reduce_only", "position_side",
              "asset_class", "client_order_id", "time_in_force", "meta"}
    return OrderRequest(**{k: v for k, v in d.items() if k in fields})
