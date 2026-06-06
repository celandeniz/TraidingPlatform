"""In-memory MockBroker — same ExecutionAdapter Protocol as the Alpaca/ccxt adapters.

A deterministic, network-free broker for tests, CI, and offline demos. Fills
every market order instantly at a price you feed it (last price per symbol),
tracks cash + positions, and computes unrealized P&L from the mark price. Supports
long AND short and honors ``reduce_only`` so a close never flips into an open.

Clean-room: written from the MockBroker concept (an OpenAlice IBroker stub), not
ported from its source.
"""
from __future__ import annotations

from .base import OrderRequest, OrderResult, PositionView


class _Pos:
    __slots__ = ("qty", "avg_entry")

    def __init__(self, qty: float, avg_entry: float):
        self.qty = qty            # signed: >0 long, <0 short
        self.avg_entry = avg_entry


class MockExecutionAdapter:
    """Deterministic in-memory broker.

    Prices come from ``mark()`` (or the order's ``meta['price']``); with neither,
    fills use the position's average entry as a last resort so tests stay total.
    """

    def __init__(self, starting_cash: float = 100_000.0, asset_class: str = "equity",
                 *, realistic: bool = False, fill_config=None):
        self._cash = float(starting_cash)
        self._asset_class = asset_class
        self._positions: dict[str, _Pos] = {}
        self._marks: dict[str, float] = {}
        self._orders: list[OrderResult] = []
        self._seq = 0
        # When realistic=True, fills route through the FillModel (order types,
        # spread/slippage, partial fills). Default off keeps the deterministic
        # full-fill-at-one-price behavior the existing tests rely on.
        self._realistic = realistic
        if realistic:
            from .fills import FillModelConfig

            self._fill_cfg = fill_config or FillModelConfig()
        else:
            self._fill_cfg = None

    # --- test/demo helpers -------------------------------------------------
    def mark(self, symbol: str, price: float) -> None:
        """Set the current price used for fills and unrealized P&L."""
        self._marks[symbol] = float(price)

    def _fill_price(self, req: OrderRequest) -> float:
        if "price" in req.meta:
            return float(req.meta["price"])
        if req.symbol in self._marks:
            return self._marks[req.symbol]
        pos = self._positions.get(req.symbol)
        return pos.avg_entry if pos else 0.0

    # --- ExecutionAdapter Protocol ----------------------------------------
    def submit(self, req: OrderRequest) -> OrderResult:
        ref = self._fill_price(req)
        if ref <= 0:
            return self._reject(req, "no price available for mock fill")

        # Decide fill qty + price: realistic (FillModel) or legacy (full @ ref).
        if self._realistic:
            from .fills import Quote, simulate_fill

            quote = Quote(ref_price=ref, volume=req.meta.get("volume"))
            fr = simulate_fill(req, quote, self._fill_cfg)
            if not fr.filled:
                return self._reject(req, f"{req.order_type} not filled: {fr.reason}")
            fill_qty, fill_px = fr.filled_qty, fr.fill_price
            status = "partial" if fr.reason == "partial" else "filled"
        else:
            fill_qty, fill_px, status = req.qty, ref, "filled"

        signed = fill_qty if req.side == "buy" else -fill_qty
        pos = self._positions.get(req.symbol)
        cur_qty = pos.qty if pos else 0.0

        if req.reduce_only:
            # A reduce-only order may only shrink an existing position toward 0.
            if cur_qty == 0 or (cur_qty > 0) == (signed > 0):
                return self._reject(req, "reduce_only order would not reduce position")
            # clamp so we never cross zero into a new opposite position
            signed = max(-abs(cur_qty), min(abs(cur_qty), signed))
            fill_qty = abs(signed)

        new_qty = cur_qty + signed
        # realized cash flow: buying costs cash, selling returns cash (qty * fill price)
        self._cash -= signed * fill_px

        if abs(new_qty) < 1e-12:
            self._positions.pop(req.symbol, None)
        elif pos is None or (cur_qty == 0):
            self._positions[req.symbol] = _Pos(new_qty, fill_px)
        elif (cur_qty > 0) == (new_qty > 0) and abs(new_qty) > abs(cur_qty):
            # adding to the same side -> weighted-average entry
            total = pos.avg_entry * abs(cur_qty) + fill_px * abs(signed)
            pos.avg_entry = total / abs(new_qty)
            pos.qty = new_qty
        else:
            # reducing, or flipping side -> entry resets to fill on a flip
            pos.qty = new_qty
            if (cur_qty > 0) != (new_qty > 0):
                pos.avg_entry = fill_px

        self._marks[req.symbol] = ref
        self._seq += 1
        res = OrderResult(
            ok=True, order_id=f"mock-{self._seq}", symbol=req.symbol,
            side=req.side, qty=req.qty, status=status,
            detail=f"{status} {fill_qty} @ {round(fill_px, 6)}",
            filled_qty=fill_qty, fill_price=fill_px,
        )
        self._orders.append(res)
        return res

    def _reject(self, req: OrderRequest, detail: str) -> OrderResult:
        return OrderResult(
            ok=False, order_id=None, symbol=req.symbol, side=req.side,
            qty=req.qty, status="rejected", detail=detail,
        )

    def list_positions(self) -> list[PositionView]:
        out: list[PositionView] = []
        for sym, pos in self._positions.items():
            mark = self._marks.get(sym, pos.avg_entry)
            side = "long" if pos.qty > 0 else "short"
            # P&L is +ve when mark moves in the position's favor (sign handles short)
            upl = (mark - pos.avg_entry) * pos.qty
            cost = abs(pos.avg_entry * pos.qty)
            uplpc = (upl / cost * 100) if cost else 0.0
            out.append(PositionView(
                symbol=sym, qty=abs(pos.qty), side=side, avg_entry=pos.avg_entry,
                current=mark, unrealized_pl=upl, unrealized_plpc=uplpc,
            ))
        return out

    def account_summary(self) -> dict:
        positions = self.list_positions()
        notional = sum(abs((p["current"] or 0) * p["qty"]) for p in positions)
        # equity = cash + market value of holdings (signed: longs add, shorts subtract)
        mkt_value = sum(
            self._marks.get(sym, pos.avg_entry) * pos.qty
            for sym, pos in self._positions.items()
        )
        equity = self._cash + mkt_value
        return {
            "status": "active",
            "cash": self._cash,
            "equity": equity,
            "buying_power": self._cash,
            "positions_notional": notional,
            "open_positions": len(positions),
        }
