"""Execution adapter interface — the seam that keeps paper/live swappable.

Phase 1 ships only a paper adapter (Alpaca paper). A live adapter implements the
same Protocol later; the rest of the system stays mode-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

Side = Literal["buy", "sell"]


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    qty: float


@dataclass
class OrderResult:
    ok: bool
    order_id: str | None
    symbol: str
    side: str
    qty: float
    status: str
    detail: str = ""


class ExecutionAdapter(Protocol):
    def submit(self, req: OrderRequest) -> OrderResult: ...
