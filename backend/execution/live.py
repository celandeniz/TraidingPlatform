"""LIVE (real-money) execution — gated three ways, ALL required.

1. LIVE_TRADING=true env flag (settings.live_trading) — else construction refuses.
2. Per-order confirmation callback — submit() blocks unless confirm(req) is True.
3. Must be built INSIDE a RiskManager (the caller enforces this; never return a
   live adapter un-wrapped).

Shares order mapping with the paper/ccxt adapters; the only real difference is
paper=False / sandbox=False. Real-money short/leverage is high risk.
"""
from __future__ import annotations

from typing import Callable, Optional

from .base import OrderRequest, OrderResult, PositionView


class LiveTradingDisabled(RuntimeError):
    pass


class AlpacaLiveExecutionAdapter:
    """Alpaca live (paper=False). Requires live_trading flag + confirm callback."""

    def __init__(self, api_key: str, api_secret: str, *, live_trading: bool,
                 confirm: Optional[Callable[[OrderRequest], bool]] = None):
        if not live_trading:
            raise LiveTradingDisabled("LIVE_TRADING is not enabled")
        from alpaca.trading.client import TradingClient

        self._client = TradingClient(api_key, api_secret, paper=False)
        self._confirm = confirm

    def submit(self, req: OrderRequest) -> OrderResult:
        if self._confirm is not None and not self._confirm(req):
            return OrderResult(False, None, req.symbol, req.side, req.qty,
                               "unconfirmed", "live order not confirmed")
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        try:
            order = self._client.submit_order(MarketOrderRequest(
                symbol=req.symbol, qty=req.qty,
                side=OrderSide.BUY if req.side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            ))
            return OrderResult(True, str(order.id), req.symbol, req.side, req.qty,
                               str(order.status))
        except Exception as exc:  # noqa: BLE001
            return OrderResult(False, None, req.symbol, req.side, req.qty,
                               "rejected", str(exc))

    def list_positions(self) -> list[PositionView]:
        out: list[PositionView] = []
        for p in self._client.get_all_positions():
            out.append(PositionView(
                symbol=p.symbol, qty=float(p.qty), side=str(p.side),
                avg_entry=float(p.avg_entry_price),
                current=float(p.current_price) if p.current_price else None,
                unrealized_pl=float(p.unrealized_pl) if p.unrealized_pl else 0.0,
                unrealized_plpc=float(p.unrealized_plpc) * 100 if p.unrealized_plpc else 0.0,
            ))
        return out

    def account_summary(self) -> dict:
        a = self._client.get_account()
        return {"status": str(a.status), "cash": float(a.cash),
                "equity": float(a.equity), "buying_power": float(a.buying_power)}


def build_live_executor(asset_class, settings, cfg, *, confirm=None):
    """Construct a live adapter ONLY if live_trading is set. Crypto live = ccxt
    with sandbox=False. The caller MUST wrap this in a RiskManager."""
    if not getattr(settings, "live_trading", False):
        raise LiveTradingDisabled("LIVE_TRADING is not enabled")
    if asset_class == "crypto":
        from .ccxt_adapter import CcxtExecutionAdapter

        c = cfg.get("brokers", {}).get("crypto", {})
        return CcxtExecutionAdapter(
            exchange=getattr(settings, "ccxt_exchange", "binance"),
            api_key=getattr(settings, "ccxt_api_key", ""),
            api_secret=getattr(settings, "ccxt_api_secret", ""),
            sandbox=False, default_leverage=c.get("leverage", 1),
        )
    return AlpacaLiveExecutionAdapter(
        settings.alpaca_api_key, settings.alpaca_api_secret,
        live_trading=True, confirm=confirm,
    )
