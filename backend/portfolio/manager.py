"""PositionManager — opens positions from Decisions and runs the per-bar exit loop.

It never talks to a broker directly: it's handed an ExecutionAdapter (in
production the RiskManager-wrapped adapter) plus a clock and a market calendar,
so it stays unit-testable with a fake executor and synthetic bars.

Holds at most one position per symbol (v1). CALL/PUT/NONE decisions are no-ops
here — options have a separate lifecycle (out of scope this phase); the seam is
left clean.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from ..execution.base import AssetClass, ExecutionAdapter, OrderRequest, OrderResult, PositionView
from ..research.base import Decision
from .exits import evaluate_exits
from .position import Position, close_side, unrealized_pl, unrealized_pl_pct, update_high_water


@dataclass
class ExitConfig:
    take_profit_pct: float = 1.5
    stop_loss_pct: float = 1.0
    trailing_stop_pct: Optional[float] = 0.8
    time_stop_minutes: Optional[int] = 120
    opposite_signal_close: bool = True
    eod_flat_equity: bool = True


_ACTION_TO_SIDE = {"SPOT_LONG": "long", "SPOT_SHORT": "short"}


class PositionManager:
    def __init__(
        self,
        executor: ExecutionAdapter,
        *,
        clock: Callable[[], datetime],
        market_is_closing: Callable[[datetime, int], bool],
        exit_cfg: ExitConfig,
        eod_flat_minutes: int = 10,
        reflection=None,        # ReflectionMemory | None — learns from closes (opt-in)
    ):
        self.executor = executor
        self.clock = clock
        self.market_is_closing = market_is_closing
        self.exit_cfg = exit_cfg
        self.eod_flat_minutes = eod_flat_minutes
        self.reflection = reflection
        self.positions: dict[str, Position] = {}

    # ---- opening ----------------------------------------------------------
    def open_from_decision(
        self, decision: Decision, mark: float, qty: float,
        asset_class: AssetClass = "equity",
    ) -> Optional[OrderResult]:
        side = _ACTION_TO_SIDE.get(decision.action)
        if side is None or qty <= 0:
            return None  # CALL/PUT/NONE or nothing to size
        if decision.symbol in self.positions:
            return None  # already holding (opposite-signal close handled in manage())

        order_side = "buy" if side == "long" else "sell"
        req = OrderRequest(
            symbol=decision.symbol, side=order_side, qty=qty,
            position_side=side, asset_class=asset_class,
            meta={"decision_id": decision.symbol},
        )
        result = self.executor.submit(req)
        if result.ok:
            self.positions[decision.symbol] = Position(
                symbol=decision.symbol, asset_class=asset_class, side=side,
                qty=qty, avg_entry=mark, opened_at=self.clock(),
                take_profit_pct=self.exit_cfg.take_profit_pct,
                stop_loss_pct=self.exit_cfg.stop_loss_pct,
                trailing_stop_pct=self.exit_cfg.trailing_stop_pct,
                time_stop_minutes=self.exit_cfg.time_stop_minutes,
                decision_id=decision.symbol,
                tags={"rationale": decision.rationale},  # kept for reflection on close
            )
        return result

    # ---- managing ---------------------------------------------------------
    def manage(self, symbol: str, mark: float, opposite_signal: bool = False) -> Optional[OrderResult]:
        pos = self.positions.get(symbol)
        if pos is None:
            return None

        update_high_water(pos, mark)
        now = self.clock()
        closing = (
            self.exit_cfg.eod_flat_equity
            and pos.asset_class == "equity"
            and self.market_is_closing(now, self.eod_flat_minutes)
        )
        decision = evaluate_exits(
            pos, mark, now,
            opposite_signal=opposite_signal and self.exit_cfg.opposite_signal_close,
            market_is_closing=closing,
        )
        if not decision.should_exit:
            return None

        req = OrderRequest(
            symbol=symbol, side=close_side(pos), qty=pos.qty,
            reduce_only=True, position_side=pos.side, asset_class=pos.asset_class,
            meta={"exit_reason": decision.reason},
        )
        result = self.executor.submit(req)
        if result.ok:
            self._reflect_on_close(pos, mark, decision.reason or "exit")
            self.positions.pop(symbol, None)
        return result

    def _reflect_on_close(self, pos: Position, mark: float, reason: str) -> None:
        """Best-effort: hand the closed trade to reflection memory (never raises)."""
        if self.reflection is None:
            return
        try:
            from ..research.reflection import TradeClosure

            self.reflection.record_closure(TradeClosure(
                symbol=pos.symbol, side=pos.side, entry=pos.avg_entry, exit=mark,
                ret_pct=unrealized_pl_pct(pos, mark), opened_at=str(pos.opened_at),
                closed_at=str(self.clock()), exit_reason=reason,
                rationale=(pos.tags or {}).get("rationale", ""),
            ))
        except Exception:  # noqa: BLE001 - reflection is non-critical
            pass

    # ---- views ------------------------------------------------------------
    def local_view(self, marks: dict[str, float]) -> list[PositionView]:
        out: list[PositionView] = []
        for sym, pos in self.positions.items():
            mark = marks.get(sym, pos.avg_entry)
            out.append(
                PositionView(
                    symbol=sym, qty=pos.qty, side=pos.side, avg_entry=pos.avg_entry,
                    current=mark, unrealized_pl=unrealized_pl(pos, mark),
                    unrealized_plpc=unrealized_pl_pct(pos, mark),
                )
            )
        return out
