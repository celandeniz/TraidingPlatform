"""Pluggable strategy interfaces.

Two kinds of strategy:
  * SignalStrategy    -> decides a direction (buy/sell/None) on the primary window.
  * ConfirmationStrategy -> grades an already-fired signal; cannot create one.

Both receive a BarContext and never touch the broker directly — multi-timeframe
bar access goes through ctx.get_bars(...). This keeps strategies pure-ish and
testable: hand a fake context in tests, no network required.

Adding a strategy: implement one of these Protocols, register a key in
registry.py, list the key in config.yaml. The runner needs no changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional, Protocol

import pandas as pd

Side = Literal["buy", "sell"]


@dataclass
class BarContext:
    """Everything a strategy may need for one evaluation, on one symbol."""

    symbol: str
    window: pd.DataFrame  # rolling primary-timeframe (1m) bars, oldest..newest
    config: dict  # resolved config.yaml
    # Lazy multi-timeframe access (e.g. "5m", "1h"); returns oldest..newest bars.
    get_bars: Callable[[str, int], pd.DataFrame]


@dataclass
class StrategySignal:
    side: Optional[Side] = None
    strength: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def fired(self) -> bool:
        return self.side is not None


@dataclass
class Confirmation:
    name: str
    score: float
    passed: bool
    meta: dict = field(default_factory=dict)


class SignalStrategy(Protocol):
    name: str

    def evaluate(self, ctx: BarContext) -> StrategySignal: ...


class ConfirmationStrategy(Protocol):
    name: str

    def confirm(self, side: Side, ctx: BarContext) -> Confirmation: ...


@dataclass
class UniverseContext:
    """Cross-sectional view handed to a PortfolioStrategy at one rebalance date.

    frames hold DAILY bars per symbol, truncated to <= date (engine guarantees
    no future rows — same anti-lookahead contract as BarContext)."""

    date: pd.Timestamp
    frames: dict  # symbol -> daily OHLCV DataFrame, index <= date
    config: dict = field(default_factory=dict)


class PortfolioStrategy(Protocol):
    """Returns target weights {symbol: weight}; weights sum <= 1.0, remainder is
    cash. Empty dict = 100% cash. Never touches a broker."""

    name: str

    def rebalance(self, ctx: UniverseContext) -> dict: ...
