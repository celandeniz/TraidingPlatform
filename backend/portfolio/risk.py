"""RiskManager — guard layer that WRAPS any ExecutionAdapter and IS one.

Decorator pattern: it satisfies the ExecutionAdapter Protocol, so it slots in
transparently in front of paper / ccxt / live adapters. Pre-trade guards reject
unsafe OPENING orders; closing (reduce_only) orders bypass the open-side guards
so the kill-switch can never trap you in a position you can't exit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from ..execution.base import ExecutionAdapter, OrderRequest, OrderResult, PositionView


@dataclass
class RiskConfig:
    enabled: bool = False
    risk_per_trade_pct: float = 0.5
    max_concurrent_positions: int = 5
    max_position_pct: float = 20.0  # cap single-position notional as % of equity
    max_daily_loss_pct: float = 3.0  # kill-switch trips here


def position_size(equity: float, entry: float, stop: float, risk_pct: float,
                  max_position_pct: float) -> float:
    """Shares/contracts so that a stop-out loses ~risk_pct of equity, capped by
    max_position_pct notional. Pure."""
    if entry <= 0 or equity <= 0:
        return 0.0
    per_unit_risk = abs(entry - stop)
    if per_unit_risk <= 0:
        risk_qty = 0.0
    else:
        risk_qty = (equity * risk_pct / 100.0) / per_unit_risk
    notional_cap_qty = (equity * max_position_pct / 100.0) / entry
    return max(0.0, min(risk_qty, notional_cap_qty))


class RiskManager:
    def __init__(
        self,
        inner: ExecutionAdapter,
        cfg: RiskConfig,
        *,
        is_market_open: Optional[Callable[[datetime], bool]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._inner = inner
        self.cfg = cfg
        self._is_market_open = is_market_open
        self._clock = clock
        self._kill = False
        self._kill_reason = ""
        self._daily_start_equity: Optional[float] = None

    # ---- kill-switch / daily loss ----------------------------------------
    def engage_kill_switch(self, reason: str) -> None:
        self._kill = True
        self._kill_reason = reason

    @property
    def killed(self) -> bool:
        return self._kill

    def on_mark(self, equity_now: float) -> None:
        """Call each bar with current equity to track daily loss."""
        if self._daily_start_equity is None:
            self._daily_start_equity = equity_now
            return
        if self._daily_start_equity <= 0:
            return
        dd_pct = (equity_now / self._daily_start_equity - 1.0) * 100.0
        if dd_pct <= -abs(self.cfg.max_daily_loss_pct):
            self.engage_kill_switch(f"daily loss {dd_pct:.2f}% <= -{self.cfg.max_daily_loss_pct}%")

    def reset_daily(self, equity: Optional[float] = None) -> None:
        self._daily_start_equity = equity
        self._kill = False
        self._kill_reason = ""

    # ---- ExecutionAdapter Protocol ---------------------------------------
    def submit(self, req: OrderRequest) -> OrderResult:
        # Closing orders always pass — you can always exit.
        if req.reduce_only:
            return self._inner.submit(req)

        if self._kill:
            return self._blocked(req, f"kill-switch engaged: {self._kill_reason}")

        # Market-hours gate (equity only; crypto callers pass no checker / always-open).
        if self._is_market_open is not None and req.asset_class == "equity":
            now = self._clock() if self._clock else None
            if now is not None and not self._is_market_open(now):
                return self._blocked(req, "market closed")

        # Max concurrent positions (opening orders only).
        try:
            open_count = len(self._inner.list_positions())
        except Exception:  # noqa: BLE001 - if broker view fails, be conservative
            open_count = self.cfg.max_concurrent_positions
        if open_count >= self.cfg.max_concurrent_positions:
            return self._blocked(req, f"max concurrent positions ({self.cfg.max_concurrent_positions})")

        return self._inner.submit(req)

    def list_positions(self) -> list[PositionView]:
        return self._inner.list_positions()

    def account_summary(self) -> dict:
        return self._inner.account_summary()

    @staticmethod
    def _blocked(req: OrderRequest, detail: str) -> OrderResult:
        return OrderResult(
            ok=False, order_id=None, symbol=req.symbol, side=req.side,
            qty=req.qty, status="blocked", detail=detail,
        )
