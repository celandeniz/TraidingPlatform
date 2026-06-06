"""Unified news aggregator — pure, no network (fake sources)."""
from datetime import datetime, timezone

from backend.research.news_aggregator import UnifiedNews
from backend.research.news_provider import Headline

UTC = timezone.utc


def _h(title, when, url="", summary=""):
    return Headline(symbol="", headline=title, summary=summary,
                    created_at=datetime(2024, 1, when, tzinfo=UTC), url=url)


class _FakeAlpaca:
    def recent_headlines(self, symbol, limit=10):
        return [_h("Alpaca: NVDA upgrade", 3, url="http://a/1")]


class _FakeYahoo:
    def get_news(self, symbol, limit=20):
        return [_h("Yahoo: NVDA earnings beat", 4, url="http://y/2"),
                _h("Alpaca: NVDA upgrade", 3, url="http://a/1")]  # dup of alpaca by url


class _FakeRss:
    def _read_archive(self):
        return [_h("Fed holds rates", 2, url="http://r/3", summary="central bank")]

    def search(self, kw, limit=50):
        return [h for h in self._read_archive() if kw.lower() in h.headline.lower()]


def test_latest_merges_dedups_and_sorts_newest_first():
    u = UnifiedNews(alpaca=_FakeAlpaca(), rss=_FakeRss(), yahoo=_FakeYahoo())
    items = u.latest(symbol="NVDA", limit=10)
    # 3 unique (the duplicate http://a/1 collapses)
    assert len(items) == 3
    assert items[0].headline.startswith("Yahoo")        # Jan 4 newest first
    assert items[-1].headline == "Fed holds rates"      # Jan 2 oldest


def test_sources_lists_active():
    assert UnifiedNews(yahoo=_FakeYahoo()).sources() == ["yahoo"]
    assert set(UnifiedNews(alpaca=_FakeAlpaca(), rss=_FakeRss()).sources()) == {"alpaca", "rss"}


def test_search_matches_across_sources():
    u = UnifiedNews(alpaca=_FakeAlpaca(), rss=_FakeRss(), yahoo=_FakeYahoo())
    # RSS is market-wide -> "fed" matches with no symbol
    assert any("Fed" in h.headline for h in u.search("fed"))
    # Yahoo/Alpaca are per-symbol -> pass symbol to include them
    assert any("earnings" in h.headline.lower() for h in u.search("earnings", symbol="NVDA"))
    assert u.search("nonexistent-xyz", symbol="NVDA") == []


def test_empty_aggregator_is_safe():
    u = UnifiedNews()
    assert u.latest() == [] and u.search("x") == [] and u.sources() == []
