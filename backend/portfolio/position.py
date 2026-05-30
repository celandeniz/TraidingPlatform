"""Position state + sign-aware P&L. Pure, no I/O — easy to unit test.

A short position uses the same formulas as a long with the direction sign
flipped, so one `direction` multiplier covers both everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..execution.base import AssetClass, PositionSide


@dataclass
class Position:
    symbol: str
    asset_class: AssetClass
    side: PositionSide  # "long" | "short"
    qty: float  # always positive; `side` carries direction
    avg_entry: float
    opened_at: datetime  # tz-aware UTC
    # exit-rule config + state
    take_profit_pct: float
    stop_loss_pct: float
    trailing_stop_pct: Optional[float] = None
    time_stop_minutes: Optional[int] = None
    high_water: float = 0.0  # best price seen in our favor (favorable extreme)
    decision_id: Optional[str] = None
    tags: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Seed the favorable extreme at entry so trailing stops have a baseline.
        if self.high_water == 0.0:
            self.high_water = self.avg_entry


def direction(side: PositionSide) -> float:
    return 1.0 if side == "long" else -1.0


def unrealized_pl(pos: Position, mark: float) -> float:
    """Dollar P&L. Long: (mark-entry)*qty; short: (entry-mark)*qty."""
    return (mark - pos.avg_entry) * pos.qty * direction(pos.side)


def unrealized_pl_pct(pos: Position, mark: float) -> float:
    """Percent P&L relative to entry, sign-aware for shorts."""
    if pos.avg_entry == 0:
        return 0.0
    return direction(pos.side) * (mark / pos.avg_entry - 1.0) * 100.0


def update_high_water(pos: Position, mark: float) -> None:
    """Track the most-favorable price seen (max for long, min for short)."""
    if pos.side == "long":
        pos.high_water = max(pos.high_water, mark)
    else:
        pos.high_water = min(pos.high_water, mark)


def close_side(pos: Position):
    """The order side that flattens this position."""
    return "sell" if pos.side == "long" else "buy"
