"""Composable pre-trade guard pipeline — the OpenAlice "Guard pipeline" concept.

A Guard is a small object that inspects an opening order and either allows it
(returns None) or rejects it (returns a reason string). GuardPipeline holds an
ordered list of guards, satisfies the ExecutionAdapter Protocol, and runs the
guards before delegating to an inner adapter — exactly the decorator pattern the
RiskManager already uses, so the two stack cleanly:

    GuardPipeline(RiskManager(broker), guards=[whitelist, cooldown])

Closing (reduce_only) orders bypass the guards so an exit is never blocked, the
same discipline as the RiskManager.

Net-new guards vs. the existing RiskManager: a per-account symbol whitelist and a
cooldown between trades on the same symbol. Clean-room from the OpenAlice concept.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from ..execution.base import ExecutionAdapter, OrderRequest, OrderResult, PositionView


class Guard(Protocol):
    name: str

    def check(self, req: OrderRequest, adapter: ExecutionAdapter) -> Optional[str]:
        """Return a rejection reason, or None to allow."""
        ...


class SymbolWhitelistGuard:
    """Reject opening orders for symbols not on the allow-list. Empty list = allow all."""

    name = "symbol_whitelist"

    def __init__(self, allow: list[str] | set[str] | None):
        self._allow = {s.upper() for s in (allow or [])}

    def check(self, req: OrderRequest, adapter: ExecutionAdapter) -> Optional[str]:
        if not self._allow:
            return None
        if req.symbol.upper() not in self._allow:
            return f"symbol {req.symbol} not in whitelist"
        return None


class CooldownGuard:
    """Reject a new opening order on a symbol within ``seconds`` of the last one."""

    name = "cooldown"

    def __init__(self, seconds: float, clock: Optional[Callable[[], datetime]] = None):
        self._seconds = float(seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last: dict[str, datetime] = {}

    def check(self, req: OrderRequest, adapter: ExecutionAdapter) -> Optional[str]:
        if self._seconds <= 0:
            return None
        now = self._clock()
        last = self._last.get(req.symbol)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < self._seconds:
                return (f"cooldown: {elapsed:.0f}s since last {req.symbol} trade "
                        f"(need {self._seconds:.0f}s)")
        return None

    def record(self, symbol: str) -> None:
        """Stamp a successful opening fill so the cooldown window starts."""
        self._last[symbol] = self._clock()


class GuardPipeline:
    """ExecutionAdapter that runs guards on opening orders, then delegates."""

    def __init__(self, inner: ExecutionAdapter, guards: list[Guard]):
        self._inner = inner
        self.guards = guards

    def submit(self, req: OrderRequest) -> OrderResult:
        if req.reduce_only:  # exits always pass
            return self._inner.submit(req)
        for g in self.guards:
            reason = g.check(req, self._inner)
            if reason:
                return OrderResult(
                    ok=False, order_id=None, symbol=req.symbol, side=req.side,
                    qty=req.qty, status="blocked", detail=f"[{g.name}] {reason}",
                )
        res = self._inner.submit(req)
        # On a successful opening fill, let stateful guards (cooldown) record it.
        if res.ok:
            for g in self.guards:
                rec = getattr(g, "record", None)
                if callable(rec):
                    rec(req.symbol)
        return res

    def list_positions(self) -> list[PositionView]:
        return self._inner.list_positions()

    def account_summary(self) -> dict:
        return self._inner.account_summary()


def build_guard_pipeline(inner: ExecutionAdapter, cfg: dict,
                         clock: Optional[Callable[[], datetime]] = None) -> ExecutionAdapter:
    """Wrap ``inner`` in a GuardPipeline from the ``guards:`` config namespace.

    Returns ``inner`` unchanged when guards are disabled or none are configured,
    so the default path is a no-op (mirrors risk.enabled discipline).
    """
    g = cfg.get("guards", {}) or {}
    if not g.get("enabled"):
        return inner
    guards: list[Guard] = []
    whitelist = g.get("symbol_whitelist") or []
    if whitelist:
        guards.append(SymbolWhitelistGuard(whitelist))
    cooldown = float(g.get("cooldown_seconds", 0) or 0)
    if cooldown > 0:
        guards.append(CooldownGuard(cooldown, clock=clock))
    if not guards:
        return inner
    return GuardPipeline(inner, guards)
