"""Defensive parsing of a Vibe order *proposal* into our order vocabulary.

Vibe never executes for us; at most it emits an order idea (shape undefined and
internal). from_vibe_dict() maps a loose dict into a strict VibeOrderProposal or
raises ValueError — the execution router rejects anything that doesn't parse
BEFORE it can reach the OMS. Treat any field we don't understand as absent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Vibe / generic synonyms -> our canonical args.
_SYMBOL_KEYS = ("symbol", "ticker", "asset", "instrument")
_SIDE_KEYS = ("side", "action", "direction", "signal")
_QTY_KEYS = ("qty", "quantity", "shares", "size", "amount", "units")
_REDUCE_KEYS = ("reduce_only", "reduceOnly", "close", "exit")

# Directional words -> buy/sell.
_BUY = {"buy", "long", "bull", "bullish", "accumulate", "add"}
_SELL = {"sell", "short", "bear", "bearish", "reduce", "trim", "exit", "close"}


@dataclass(frozen=True)
class VibeOrderProposal:
    symbol: str
    side: str          # "buy" | "sell"
    qty: float
    reduce_only: bool = False
    rationale: str = ""

    @classmethod
    def from_vibe_dict(cls, d: dict) -> "VibeOrderProposal":
        if not isinstance(d, dict):
            raise ValueError("proposal must be a dict")

        symbol = _first_str(d, _SYMBOL_KEYS)
        if not symbol:
            raise ValueError("missing symbol")

        raw_side = _first_str(d, _SIDE_KEYS).lower()
        if raw_side in _BUY:
            side = "buy"
        elif raw_side in _SELL:
            side = "sell"
        else:
            raise ValueError(f"unrecognized side: {raw_side or '(none)'}")

        qty = _first_num(d, _QTY_KEYS)
        if qty is None or not math.isfinite(qty) or qty <= 0:
            raise ValueError(f"qty must be a positive finite number, got {qty!r}")

        reduce_only = bool(_first(d, _REDUCE_KEYS, default=False))
        rationale = _first_str(d, ("rationale", "reason", "note", "thesis"))
        return cls(symbol=symbol.upper(), side=side, qty=float(qty),
                   reduce_only=reduce_only, rationale=rationale)


def _first(d: dict, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _first_str(d: dict, keys) -> str:
    v = _first(d, keys)
    return str(v).strip() if isinstance(v, (str, int, float)) else ""


def _first_num(d: dict, keys):
    v = _first(d, keys)
    if isinstance(v, bool):  # bool is an int subclass — reject
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None
