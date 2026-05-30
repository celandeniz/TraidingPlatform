"""Shared types for the AI decision & research layer.

These are plain dataclasses so the non-LLM parts (catalyst gate, decision layer)
stay pure and unit-testable, and the LLM parts have a stable shape to fill in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

GateVerdict = Literal["ALLOW", "WITH_TREND_ONLY", "SUPPRESS"]
Action = Literal["SPOT_LONG", "CALL", "PUT", "NONE"]
Side = Literal["buy", "sell"]
CatalystTag = Literal["earnings", "news", "macro", "none"]


@dataclass
class CatalystVerdict:
    """Output of the fast (no-LLM) catalyst gate."""

    verdict: GateVerdict
    reasons: list[str] = field(default_factory=list)
    news_count: int = 0
    earnings_in_days: Optional[int] = None
    block_options: bool = False  # pre-earnings IV-crush guard


@dataclass
class ResearchContext:
    """Output of the on-demand 'why is it moving' co-pilot."""

    symbol: str
    summary: str
    tag: CatalystTag
    headlines: list[str] = field(default_factory=list)
    gate: Optional[GateVerdict] = None
    rationale: str = ""


@dataclass
class FundamentalScore:
    """Best-effort fundamental tilt: +1 long-friendly .. -1 short-friendly."""

    score: float
    label: str
    rationale: str
    available: bool = True  # False when coverage is missing -> treated neutral


@dataclass
class PersonaVote:
    name: str
    side: Literal["long", "short", "pass"]
    confidence: float  # 0..1
    rationale: str


@dataclass
class Decision:
    """Final decision object consumed by Phase 3 execution later."""

    symbol: str
    action: Action
    gate: GateVerdict
    side: Optional[Side]
    rationale: str
    confirmations: dict = field(default_factory=dict)
