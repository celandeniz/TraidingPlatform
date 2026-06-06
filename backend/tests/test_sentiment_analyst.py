"""Committee sentiment-news analyst — no network (fake LLM client)."""
from backend.research.agents.analysts import (
    SentimentNewsAnalyst,
    run_analysts,
)
from backend.research.base import CatalystVerdict


class _FakeLLM:
    """Returns a fixed structured vote; records the systems it was asked with."""
    def __init__(self, vote=None):
        self._vote = vote or {"side": "long", "confidence": 0.7, "rationale": "bullish tone"}
        self.systems = []

    def structured(self, *, system, user, **kw):
        self.systems.append(system)
        return dict(self._vote)


def _gate():
    return CatalystVerdict(verdict="ALLOW", reasons=["none"], news_count=0,
                           earnings_in_days=None, block_options=False)


def test_sentiment_analyst_added_when_headlines_present():
    llm = _FakeLLM()
    reports = run_analysts(llm, "AAPL", context="ctx",
                           headlines=["NVDA beats earnings", "Fed steady"],
                           gate=_gate(), bb_meta={})
    roles = [r.role for r in reports]
    assert "sentiment_news" in roles
    assert "news_technical" in roles
    sn = next(r for r in reports if r.role == "sentiment_news")
    assert sn.side == "long" and sn.confidence == 0.7


def test_no_sentiment_analyst_without_headlines():
    reports = run_analysts(_FakeLLM(), "AAPL", context="ctx", headlines=[],
                           gate=_gate(), bb_meta={})
    assert "sentiment_news" not in [r.role for r in reports]
    # the base personas + news_technical still run
    assert "news_technical" in [r.role for r in reports]


def test_sentiment_analyst_has_sentiment_focused_prompt():
    assert "sentiment" in SentimentNewsAnalyst.system.lower()
    assert SentimentNewsAnalyst.name == "sentiment_news"
