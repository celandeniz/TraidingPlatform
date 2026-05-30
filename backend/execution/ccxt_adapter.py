"""ccxt crypto ExecutionAdapter — same Protocol as the Alpaca adapters.

Supports long AND short natively (crypto futures). sandbox=True targets the
exchange testnet (Binance testnet by default) — the crypto equivalent of paper.
reduce_only is passed through natively so a close can never flip into an open.
"""
from __future__ import annotations

from .base import OrderRequest, OrderResult, PositionView


class CcxtExecutionAdapter:
    def __init__(self, exchange: str = "binance", api_key: str = "", api_secret: str = "",
                 sandbox: bool = True, default_leverage: int = 1):
        import ccxt

        klass = getattr(ccxt, exchange)
        self._exchange = klass({
            "apiKey": api_key, "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if sandbox and self._exchange.has.get("sandbox", True):
            self._exchange.set_sandbox_mode(True)
        self._default_leverage = default_leverage

    def submit(self, req: OrderRequest) -> OrderResult:
        try:
            lev = req.meta.get("leverage", self._default_leverage)
            if lev and lev != 1:
                try:
                    self._exchange.set_leverage(lev, req.symbol)
                except Exception:  # noqa: BLE001 - some venues set leverage differently
                    pass
            params = {"reduceOnly": req.reduce_only} if req.reduce_only else {}
            order = self._exchange.create_order(
                req.symbol, "market", req.side, req.qty, None, params
            )
            return OrderResult(
                ok=True, order_id=str(order.get("id")), symbol=req.symbol,
                side=req.side, qty=req.qty, status=str(order.get("status", "open")),
            )
        except Exception as exc:  # noqa: BLE001 - surface broker errors to the UI
            return OrderResult(
                ok=False, order_id=None, symbol=req.symbol, side=req.side,
                qty=req.qty, status="rejected", detail=str(exc),
            )

    def list_positions(self) -> list[PositionView]:
        out: list[PositionView] = []
        try:
            positions = self._exchange.fetch_positions()
        except Exception:  # noqa: BLE001
            return out
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts == 0:
                continue
            side = "long" if (p.get("side") == "long") else "short"
            entry = float(p.get("entryPrice") or 0)
            mark = float(p.get("markPrice")) if p.get("markPrice") else None
            out.append(PositionView(
                symbol=str(p.get("symbol")), qty=contracts, side=side,
                avg_entry=entry, current=mark,
                unrealized_pl=float(p.get("unrealizedPnl") or 0.0),
                unrealized_plpc=float(p.get("percentage") or 0.0),
            ))
        return out

    def account_summary(self) -> dict:
        try:
            bal = self._exchange.fetch_balance()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "cash": 0.0, "equity": 0.0,
                    "buying_power": 0.0, "detail": str(exc)}
        total = bal.get("total", {})
        free = bal.get("free", {})
        usdt_total = float(total.get("USDT", 0) or 0)
        usdt_free = float(free.get("USDT", 0) or 0)
        return {"status": "active", "cash": usdt_free, "equity": usdt_total,
                "buying_power": usdt_free}
