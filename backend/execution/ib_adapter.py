"""Interactive Brokers ExecutionAdapter — same Protocol as the Alpaca/ccxt adapters.

Talks to a running TWS or IB Gateway over the local socket API via ``ib_async``
(the maintained successor to ib_insync). Connection is lazy: nothing happens until
the first ``submit``/``list_positions``/``account_summary`` call, so importing this
module never touches the network and the test suite stays offline.

Enable with ``brokers.equity.executor: ib`` (and a ``brokers.ib:`` block) in
config.yaml. Defaults to the TWS paper port (7497); 7496 is live TWS, 4002/4001
are the Gateway paper/live ports.

Clean-room: written against the public ib_async API docs, not from OpenAlice source.
"""
from __future__ import annotations

from .base import OrderRequest, OrderResult, PositionView


class IBExecutionAdapter:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497,
                 client_id: int = 1, account: str = ""):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._account = account
        self._ib = None  # lazily connected

    def _conn(self):
        """Return a connected IB handle, connecting on first use."""
        if self._ib is not None and self._ib.isConnected():
            return self._ib
        from ib_async import IB  # lazy import: only when IB is actually used

        ib = self._ib or IB()
        if not ib.isConnected():
            ib.connect(self._host, self._port, clientId=self._client_id)
        self._ib = ib
        return ib

    def _contract(self, symbol: str):
        from ib_async import Stock

        c = Stock(symbol, "SMART", "USD")
        self._conn().qualifyContracts(c)
        return c

    def submit(self, req: OrderRequest) -> OrderResult:
        try:
            from ib_async import MarketOrder

            ib = self._conn()
            order = MarketOrder("BUY" if req.side == "buy" else "SELL", req.qty)
            if self._account:
                order.account = self._account
            # IB has no generic stock reduce_only; tag the order so a parent OMS/
            # guard layer can still reason about intent.
            if req.reduce_only:
                order.orderRef = "reduce_only"
            trade = ib.placeOrder(self._contract(req.symbol), order)
            ib.sleep(0)  # let the event loop register the order
            status = str(trade.orderStatus.status or "submitted")
            return OrderResult(
                ok=True, order_id=str(trade.order.orderId), symbol=req.symbol,
                side=req.side, qty=req.qty, status=status,
            )
        except Exception as exc:  # noqa: BLE001 - surface broker errors to the UI
            return OrderResult(
                ok=False, order_id=None, symbol=req.symbol, side=req.side,
                qty=req.qty, status="rejected", detail=str(exc),
            )

    def list_positions(self) -> list[PositionView]:
        out: list[PositionView] = []
        try:
            ib = self._conn()
            for item in ib.portfolio():
                qty = float(item.position)
                if qty == 0:
                    continue
                out.append(PositionView(
                    symbol=item.contract.symbol,
                    qty=abs(qty),
                    side="long" if qty > 0 else "short",
                    avg_entry=float(item.averageCost or 0),
                    current=float(item.marketPrice) if item.marketPrice else None,
                    unrealized_pl=float(item.unrealizedPNL or 0.0),
                    unrealized_plpc=0.0,  # IB doesn't return a percentage directly
                ))
        except Exception:  # noqa: BLE001 - a disconnect shouldn't blank the dashboard
            return out
        return out

    def account_summary(self) -> dict:
        try:
            ib = self._conn()
            tags = {av.tag: av.value for av in ib.accountSummary(self._account or "All")}
            return {
                "status": "active",
                "cash": float(tags.get("TotalCashValue", 0) or 0),
                "equity": float(tags.get("NetLiquidation", 0) or 0),
                "buying_power": float(tags.get("BuyingPower", 0) or 0),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "cash": 0.0, "equity": 0.0,
                    "buying_power": 0.0, "detail": str(exc)}

    def close(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()
