"""Universe scanner — rank symbols by a transparent intraday buy-edge SCORE.

HONEST FRAMING: the 0-100 score is a heuristic blend of trend, momentum, RSI room,
and regime — an *estimated edge*, NOT a probability of profit and NOT a guarantee.
Every component is exposed so the ranking is explainable, never a black box.
"""
from .score import ScoreResult, score_symbol
from .scanner import Scanner

__all__ = ["score_symbol", "ScoreResult", "Scanner"]
