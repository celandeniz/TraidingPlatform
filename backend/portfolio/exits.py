"""Pure exit-rule engine (main build spec §4.5).

Given a position, the current mark, and a clock, decide whether to exit and why.
Pure: the caller decides things like `market_is_closing` (equity-only) and passes
them in, so this stays testable without a clock or calendar.

Precedence (first match wins):
  opposite_signal > eod_flat (equity) > stop_loss > trailing_stop > take_profit > time_stop
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .position import Position, direction, unrealized_pl_pct


@dataclass
class ExitDecision:
    should_exit: bool
    reason: Optional[str] = None  # take_profit|stop_loss|trailing_stop|time_stop|opposite_signal|eod_flat
    portion: float = 1.0  # 1.0 = full close (scale-out reserved for later)


def evaluate_exits(
    pos: Position,
    mark: float,
    now: datetime,
    *,
    opposite_signal: bool = False,
    market_is_closing: bool = False,
) -> ExitDecision:
    # 1) Opposite signal — a fresh reverse setup closes the position.
    if opposite_signal:
        return ExitDecision(True, "opposite_signal")

    # 2) End-of-day flat (equities only; caller passes False for crypto).
    if market_is_closing:
        return ExitDecision(True, "eod_flat")

    pl_pct = unrealized_pl_pct(pos, mark)  # already sign-aware for shorts

    # 3) Hard stop loss.
    if pl_pct <= -abs(pos.stop_loss_pct):
        return ExitDecision(True, "stop_loss")

    # 4) Trailing stop — give back at most trailing_stop_pct from the favorable extreme.
    if pos.trailing_stop_pct is not None:
        # Drawdown from high_water, measured against us (positive = adverse).
        give_back_pct = direction(pos.side) * (pos.high_water / mark - 1.0) * 100.0
        # For long: high_water>=mark -> give_back positive when price fell from peak.
        # For short: high_water<=mark -> direction(-1) flips so rising price = adverse.
        if give_back_pct >= abs(pos.trailing_stop_pct):
            return ExitDecision(True, "trailing_stop")

    # 5) Take profit.
    if pl_pct >= abs(pos.take_profit_pct):
        return ExitDecision(True, "take_profit")

    # 6) Time stop — held too long without hitting a target (theta/decay guard).
    if pos.time_stop_minutes is not None:
        held_min = (now - pos.opened_at).total_seconds() / 60.0
        if held_min >= pos.time_stop_minutes:
            return ExitDecision(True, "time_stop")

    return ExitDecision(False, None)
