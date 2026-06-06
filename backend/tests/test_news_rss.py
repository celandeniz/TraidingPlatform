"""RSS aggregator — no network. A fake feedparser stands in for the real one."""
import sys
import types
from datetime import datetime, timezone

from backend.research.news_rss import RssNewsAggregator

UTC = timezone.utc


def _install_fake_feedparser(entries_by_url):
    """Register a stub `feedparser` module returning canned entries per URL."""
    mod = types.ModuleType("feedparser")

    def parse(url):
        ns = types.SimpleNamespace()
        ns.entries = [types.SimpleNamespace(**e) for e in entries_by_url.get(url, [])]
        return ns

    mod.parse = parse
    sys.modules["feedparser"] = mod


def test_fetch_dedups_and_archive_search(tmp_path):
    _install_fake_feedparser({
        "feedA": [
            {"title": "Fed holds rates steady", "summary": "central bank pause",
             "link": "http://a/1", "published_parsed": (2024, 1, 1, 12, 0, 0, 0, 0, 0)},
            {"title": "NVDA earnings beat", "summary": "chips strong",
             "link": "http://a/2", "published_parsed": (2024, 1, 2, 12, 0, 0, 0, 0, 0)},
        ],
    })
    agg = RssNewsAggregator(["feedA"], archive_path=tmp_path / "news.jsonl",
                            clock=lambda: datetime(2024, 1, 3, tzinfo=UTC))
    fresh = agg.fetch()
    assert len(fresh) == 2
    # second fetch: same items already seen -> nothing new
    assert agg.fetch() == []

    hits = agg.search("nvda")
    assert len(hits) == 1 and "NVDA" in hits[0].headline
    assert agg.search("rates")[0].url == "http://a/1"
    assert agg.search("nonexistent") == []


def test_seen_persists_across_instances(tmp_path):
    path = tmp_path / "news.jsonl"
    _install_fake_feedparser({"f": [
        {"title": "X", "summary": "y", "link": "http://x",
         "published_parsed": (2024, 1, 1, 0, 0, 0, 0, 0, 0)}]})
    RssNewsAggregator(["f"], archive_path=path).fetch()
    # fresh instance reads the archive -> the item is already seen
    agg2 = RssNewsAggregator(["f"], archive_path=path)
    assert agg2.fetch() == []
    assert len(agg2.search("x")) == 1
