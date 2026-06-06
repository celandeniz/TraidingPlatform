"""Execution adapter interface — the seam that keeps paper/live/crypto swappable.

Every broker (Alpaca paper, Alpaca live, ccxt crypto) implements the SAME
ExecutionAdapter Protocol, so the engine, risk manager, and dashboard stay
broker-agnostic. The RiskManager (backend/portfolio/risk.py) also implements
this Protocol by wrapping an inner adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol, TypedDict

Side = Literal["buy", "sell"]
PositionSide = Literal["long", "short"]
AssetClass = Literal["equity", "crypto"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]


@dataclass
class OrderRequest:
    symbol: str
    side: Side  # buy | sell = order direction (unchanged, back-compatible)
    qty: float
    # --- additive fields, all defaulted so existing call sites keep working ---
    reduce_only: bool = False  # True = close/trim only, never open or flip
    position_side: Optional[PositionSide] = None  # opening intent; None = infer from side
    asset_class: AssetClass = "equity"
    client_order_id: Optional[str] = None  # idempotency / reconciliation
    time_in_force: str = "day"  # "day" for equity, "gtc" for crypto
    # --- order type (default market keeps every existing call site working) ---
    order_type: OrderType = "market"
    limit_price: Optional[float] = None  # required for limit / stop_limit
    stop_price: Optional[float] = None   # trigger for stop / stop_limit
    meta: dict = field(default_factory=dict)  # leverage, decision id, tags


@dataclass
class OrderResult:
    ok: bool
    order_id: str | None
    symbol: str
    side: str
    qty: float
    status: str
    detail: str = ""
    # --- realistic-fill fields (None when a broker doesn't report them) ---
    filled_qty: Optional[float] = None   # may be < qty on a partial fill
    fill_price: Optional[float] = None   # average fill price actually realized


class PositionView(TypedDict):
    """The position shape the dashboard already consumes. Every adapter returns
    a list of these so the frontend never changes regardless of broker."""

    symbol: str
    qty: float
    side: str  # "long" | "short"
    avg_entry: float
    current: Optional[float]
    unrealized_pl: float
    unrealized_plpc: float


class ExecutionAdapter(Protocol):
    def submit(self, req: OrderRequest) -> OrderResult: ...

    def list_positions(self) -> list[PositionView]: ...

    def account_summary(self) -> dict: ...
