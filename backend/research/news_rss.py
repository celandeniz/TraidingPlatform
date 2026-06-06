"""RSS news aggregation with a searchable archive.

Background-collected RSS headlines (via feedparser, lazy-imported) persisted to an
append-only JSONL archive (logs/news_archive.jsonl) with keyword search — the
OpenAlice news concept, alongside the existing Alpaca news provider. Reuses the
shared ``Headline`` shape so the catalyst gate consumes both identically.

Clean-room: written against the feedparser API + the RSS concept, not OpenAlice.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..settings import REPO_DIR
from .news_provider import Headline

ARCHIVE_PATH = REPO_DIR / "logs" / "news_archive.jsonl"


class RssNewsAggregator:
    def __init__(self, feeds: list[str], *, archive_path: Optional[Path] = None,
                 retention_days: int = 14, clock=None):
        self._feeds = feeds or []
        self._path = archive_path or ARCHIVE_PATH
        self._retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seen: set[str] = set()
        self._load_seen()

    def _load_seen(self) -> None:
        for h in self._read_archive():
            self._seen.add(h.url or h.headline)

    def fetch(self) -> list[Headline]:
        """Pull all feeds, append unseen items to the archive, return the new ones."""
        try:
            import feedparser
        except ImportError as exc:  # pragma: no cover - dep is optional
            raise RuntimeError("RSS aggregation requires 'feedparser' "
                               "(pip install feedparser)") from exc
        fresh: list[Headline] = []
        for url in self._feeds:
            parsed = feedparser.parse(url)
            for entry in getattr(parsed, "entries", []):
                h = self._entry_to_headline(entry)
                key = h.url or h.headline
                if not key or key in self._seen:
                    continue
                self._seen.add(key)
                fresh.append(h)
        if fresh:
            self._append(fresh)
        return fresh

    def _entry_to_headline(self, entry) -> Headline:
        created = self._parse_time(entry)
        return Headline(
            symbol="",  # RSS items aren't symbol-scoped; search by keyword instead
            headline=getattr(entry, "title", "") or "",
            summary=getattr(entry, "summary", "") or getattr(entry, "description", "") or "",
            created_at=created,
            url=getattr(entry, "link", "") or "",
        )

    def _parse_time(self, entry) -> datetime:
        st = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if st is not None:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return self._clock()

    def _append(self, items: list[Headline]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            for h in items:
                fh.write(json.dumps({
                    "headline": h.headline, "summary": h.summary,
                    "created_at": h.created_at.isoformat(), "url": h.url,
                }, default=str) + "\n")

    def _read_archive(self) -> list[Headline]:
        if not self._path.exists():
            return []
        out: list[Headline] = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                created = d.get("created_at")
                try:
                    ts = datetime.fromisoformat(created) if created else self._clock()
                except ValueError:
                    ts = self._clock()
                out.append(Headline(symbol="", headline=d.get("headline", ""),
                                    summary=d.get("summary", ""), created_at=ts,
                                    url=d.get("url", "")))
        return out

    def search(self, keyword: str, limit: int = 50) -> list[Headline]:
        """Case-insensitive keyword search over archived headlines + summaries."""
        kw = keyword.lower().strip()
        if not kw:
            return []
        hits = [h for h in self._read_archive()
                if kw in h.headline.lower() or kw in h.summary.lower()]
        hits.sort(key=lambda h: h.created_at, reverse=True)
        return hits[:limit]
