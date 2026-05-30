"""Alpaca PAPER execution adapter.

Sends real orders to the Alpaca *paper* account (no real money). Market orders,
spot equity only in Phase 1. A live adapter would implement the same interface
behind LIVE_TRADING + per-order confirmation (not in Phase 1).
"""
from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from .base import OrderRequest, OrderResult


class PaperExecutionAdapter:
    def __init__(self, api_key: str, api_secret: str):
        self._client = TradingClient(api_key, api_secret, paper=True)

    def submit(self, req: OrderRequest) -> OrderResult:
        try:
            order = self._client.submit_order(
                MarketOrderRequest(
                    symbol=req.symbol,
                    qty=req.qty,
                    side=OrderSide.BUY if req.side == "buy" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
            )
            return OrderResult(
                ok=True,
                order_id=str(order.id),
                symbol=req.symbol,
                side=req.side,
                qty=req.qty,
                status=str(order.status),
            )
        except Exception as exc:  # noqa: BLE001 - surface broker errors to the UI
            return OrderResult(
                ok=False,
                order_id=None,
                symbol=req.symbol,
                side=req.side,
                qty=req.qty,
                status="rejected",
                detail=str(exc),
            )

    def list_positions(self) -> list[dict]:
        out = []
        for p in self._client.get_all_positions():
            out.append(
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "side": str(p.side),
                    "avg_entry": float(p.avg_entry_price),
                    "current": float(p.current_price) if p.current_price else None,
                    "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else 0.0,
                    "unrealized_plpc": float(p.unrealized_plpc) * 100
                    if p.unrealized_plpc
                    else 0.0,
                }
            )
        return out

    def account_summary(self) -> dict:
        a = self._client.get_account()
        return {
            "status": str(a.status),
            "cash": float(a.cash),
            "equity": float(a.equity),
            "buying_power": float(a.buying_power),
        }
