"""FillModel — realistic fill simulation for market/limit/stop orders.

Turns a desired order + a reference price (a quote, or a bar's OHLC in backtest)
into what would *actually* happen: a triggered/eligible fill at a price that
includes half-spread + slippage, possibly only partially filled when the order is
large relative to available volume. This is the core of "realistic & advanced"
automated transactions — it replaces the old "fill 100% at one clean price".

Pure and deterministic (no clock, no RNG): given the same inputs it returns the
same `FillResult`, so it's trivially unit-testable and safe for backtests.

Conventions:
  * bps are basis points (1 bp = 0.01%). Half-spread + slippage are charged
    ADVERSELY: buys fill higher, sells fill lower.
  * Slippage = base_slippage_bps + impact_coef * participation, where
    participation = requested_qty / bar_volume (0 when volume unknown). Bigger
    orders relative to volume pay more — a simple linear market-impact model.
  * Partial fills: filled_qty is capped at max_participation * bar_volume.
  * Limit orders fill only if the market trades through the limit; the fill price
    is the limit (you don't get price improvement in this conservative model).
  * Stop / stop_limit: the stop must be triggered by the bar's range first; a
    plain stop then behaves like a market order, a stop_limit like a limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import OrderRequest


@dataclass
class FillModelConfig:
    spread_bps: float = 2.0          # full bid/ask spread; half is charged per fill
    base_slippage_bps: float = 1.0   # fixed adverse slippage per fill
    impact_coef_bps: float = 50.0    # bps of slippage at 100% participation
    max_participation: float = 1.0   # cap fill at this fraction of bar volume (1 = no cap)
    commission_bps: float = 1.0      # per-side commission


@dataclass
class FillResult:
    filled: bool
    filled_qty: float = 0.0
    fill_price: float = 0.0          # average price incl. costs
    reason: str = ""                 # "filled" | "partial" | "no_cross" | "not_triggered"
    slippage_bps: float = 0.0        # adverse cost applied (half-spread + slippage + commission)


@dataclass
class Quote:
    """A reference snapshot the model fills against. For a backtest bar, pass
    open/high/low; for a live quote, pass mid and (optionally) the same as bounds."""
    ref_price: float                 # mid / arrival price the fill is measured from
    high: Optional[float] = None     # highest traded price in the interval
    low: Optional[float] = None      # lowest traded price in the interval
    volume: Optional[float] = None   # traded volume in the interval


def _cost_bps(req: OrderRequest, cfg: FillModelConfig, participation: float) -> float:
    return (cfg.spread_bps / 2.0
            + cfg.base_slippage_bps
            + cfg.impact_coef_bps * max(0.0, participation)
            + cfg.commission_bps)


def _apply(px: float, side_is_buy: bool, bps: float) -> float:
    frac = bps / 10000.0
    return px * (1 + frac) if side_is_buy else px * (1 - frac)


def simulate_fill(req: OrderRequest, quote: Quote, cfg: FillModelConfig) -> FillResult:
    """Compute the realistic fill for one order against one reference quote/bar."""
    buy = req.side == "buy"
    high = quote.high if quote.high is not None else quote.ref_price
    low = quote.low if quote.low is not None else quote.ref_price

    # --- triggering: does this order get to act at all? ---
    if req.order_type in ("stop", "stop_limit"):
        if req.stop_price is None:
            return FillResult(False, reason="not_triggered")
        # a buy-stop triggers when price rises to it; a sell-stop when it falls to it
        triggered = (high >= req.stop_price) if buy else (low <= req.stop_price)
        if not triggered:
            return FillResult(False, reason="not_triggered")

    if req.order_type in ("limit", "stop_limit"):
        if req.limit_price is None:
            return FillResult(False, reason="no_cross")
        # the market must trade through the limit: buy fills if low <= limit,
        # sell fills if high >= limit
        crossed = (low <= req.limit_price) if buy else (high >= req.limit_price)
        if not crossed:
            return FillResult(False, reason="no_cross")
        base_px = req.limit_price
    else:
        base_px = quote.ref_price  # market / plain stop fill from the reference

    # --- size / participation -> partial fills ---
    participation = 0.0
    filled_qty = req.qty
    if quote.volume and quote.volume > 0:
        participation = req.qty / quote.volume
        cap = cfg.max_participation * quote.volume
        if filled_qty > cap:
            filled_qty = cap

    bps = _cost_bps(req, cfg, participation)
    fill_price = _apply(base_px, buy, bps)
    partial = filled_qty < req.qty - 1e-12
    return FillResult(
        filled=filled_qty > 0,
        filled_qty=filled_qty,
        fill_price=fill_price,
        reason="partial" if partial else "filled",
        slippage_bps=bps,
    )
