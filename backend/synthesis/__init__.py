"""NL->strategy compiler (in-house, spec: docs/superpowers/specs/2026-06-13-
nl-strategy-compiler-design.md).

Turns a natural-language brief into best-of-N LLM-generated Python strategy
classes, validates + sandbox-backtests each, ranks them with the existing
tournament risk gates, and auto-promotes the best passing candidate to PAPER
trading. Live trading is structurally impossible from here (the promoter is
paper-only and imports no executor; strategies are broker-free by contract).

Disjoint from backend/integrations/vibe_trading/ (the external Vibe sidecar):
this is the path whose output can actually reach the paper runner.

Public entry point: pipeline.synthesize(brief, ...).
"""
from .brief import StrategyBrief
from .pipeline import SynthesisResult, synthesize

__all__ = ["StrategyBrief", "SynthesisResult", "synthesize"]
