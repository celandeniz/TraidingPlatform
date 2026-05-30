"""Fast catalyst gate — NO LLM, runs on every fired+confirmed signal.

Decides whether a fade is safe right now. The most dangerous thing a mean-reversion
fade can do is fade a real catalyst (earnings, hot news, big gap) — those moves tend
to continue. This gate suppresses or restricts fades in those windows.

Pure scoring lives in evaluate(); inputs are plain values so it is unit-testable
without any network.
"""
from __future__ import annotations

from typing import Optional

from .base import CatalystVerdict, Side


def evaluate(
    side: Side,
    *,
    regime: str,
    news_ages_minutes: list[float],
    earnings_in_days: Optional[int],
    gap_pct: Optional[float],
    news_recency_minutes: int = 30,
    earnings_block_days: int = 1,
    block_options_pre_earnings_days: int = 1,
    gap_catalyst_pct: float = 2.5,
) -> CatalystVerdict:
    """Return ALLOW / WITH_TREND_ONLY / SUPPRESS for a fade signal.

    side: the fade direction the signal wants to take (buy = fade a drop, etc.).
    regime: "up" | "down" | "range" (for WITH_TREND_ONLY filtering downstream).
    """
    reasons: list[str] = []
    block_options = False

    # 1) Earnings proximity is the hardest stop.
    if earnings_in_days is not None and earnings_in_days <= earnings_block_days:
        reasons.append(f"earnings in {earnings_in_days}d")
        if earnings_in_days <= block_options_pre_earnings_days:
            block_options = True
        return CatalystVerdict(
            verdict="SUPPRESS",
            reasons=reasons,
            news_count=len(news_ages_minutes),
            earnings_in_days=earnings_in_days,
            block_options=block_options,
        )

    hot_news = [a for a in news_ages_minutes if a <= news_recency_minutes]
    big_gap = gap_pct is not None and abs(gap_pct) >= gap_catalyst_pct

    # 2) Hot news + big gap = likely real catalyst -> suppress the fade.
    if hot_news and big_gap:
        reasons.append(f"{len(hot_news)} hot headline(s) + gap {gap_pct:.1f}%")
        verdict = "SUPPRESS"
    # 3) Hot news OR big gap alone -> only allow trend-direction trades.
    elif hot_news:
        reasons.append(f"{len(hot_news)} headline(s) < {news_recency_minutes}m")
        verdict = "WITH_TREND_ONLY"
    elif big_gap:
        reasons.append(f"abnormal gap {gap_pct:.1f}%")
        verdict = "WITH_TREND_ONLY"
    else:
        reasons.append("no catalyst detected")
        verdict = "ALLOW"

    return CatalystVerdict(
        verdict=verdict,
        reasons=reasons,
        news_count=len(news_ages_minutes),
        earnings_in_days=earnings_in_days,
        block_options=block_options,
    )
