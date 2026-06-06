"""Scheduling primitives: Schedule, Heartbeat, EventLog.

Schedule.next_fire() is pure (clock passed in) so it's trivially testable and
deterministic. Three kinds:
  - "interval": every N seconds from an anchor
  - "once":     a single timestamp
  - "cron":     a 5-field cron expression (lazy-imports croniter; raises a clear
                error if croniter isn't installed and a cron schedule is used)

Heartbeat adds active-hours filtering and a dedup window so a periodic timer only
emits during trading hours and never twice within the window.

EventLog is an append-only JSONL trail (logs/events.jsonl) of everything the
scheduler emits — the audit surface OpenAlice keeps for its cron engine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from ..settings import REPO_DIR

EVENT_LOG_PATH = REPO_DIR / "logs" / "events.jsonl"

ScheduleKind = Literal["interval", "once", "cron"]


@dataclass
class Schedule:
    name: str
    kind: ScheduleKind
    # interval
    every_seconds: Optional[float] = None
    anchor: Optional[datetime] = None
    # once
    at: Optional[datetime] = None
    # cron
    cron: Optional[str] = None

    def next_fire(self, after: datetime) -> Optional[datetime]:
        """Next fire strictly after ``after`` (tz-aware UTC), or None if never again."""
        if self.kind == "once":
            if self.at is None:
                return None
            return self.at if self.at > after else None

        if self.kind == "interval":
            if not self.every_seconds or self.every_seconds <= 0:
                return None
            anchor = self.anchor or after
            if after < anchor:
                return anchor
            elapsed = (after - anchor).total_seconds()
            steps = int(elapsed // self.every_seconds) + 1
            return anchor + timedelta(seconds=steps * self.every_seconds)

        if self.kind == "cron":
            if not self.cron:
                return None
            try:
                from croniter import croniter
            except ImportError as exc:  # pragma: no cover - dep is optional
                raise RuntimeError(
                    "cron schedules require the 'croniter' package "
                    "(pip install croniter)"
                ) from exc
            return croniter(self.cron, after).get_next(datetime)

        return None


@dataclass
class Heartbeat:
    """Periodic timer with active-hours filter + dedup window.

    ``active_start``/``active_end`` are UTC times bounding when ticks are allowed
    (inclusive start, exclusive end). ``dedup_seconds`` suppresses a tick that
    lands within the window of the previous accepted tick.
    """

    interval_seconds: float
    active_start: Optional[time] = None
    active_end: Optional[time] = None
    dedup_seconds: float = 0.0
    _last_tick: Optional[datetime] = field(default=None, repr=False)

    def _within_active_hours(self, now: datetime) -> bool:
        if self.active_start is None or self.active_end is None:
            return True
        t = now.timetz().replace(tzinfo=None)
        if self.active_start <= self.active_end:
            return self.active_start <= t < self.active_end
        # window wraps midnight
        return t >= self.active_start or t < self.active_end

    def should_tick(self, now: datetime) -> bool:
        """True if a tick is due now: in active hours and past interval + dedup."""
        if not self._within_active_hours(now):
            return False
        if self._last_tick is not None:
            elapsed = (now - self._last_tick).total_seconds()
            if elapsed < max(self.interval_seconds, self.dedup_seconds):
                return False
        return True

    def tick(self, now: datetime) -> bool:
        """Consume a tick: record + return True if accepted, else False."""
        if self.should_tick(now):
            self._last_tick = now
            return True
        return False


class EventLog:
    """Append-only JSONL event trail for scheduler emissions."""

    def __init__(self, path: Optional[Path] = None, clock=None):
        self._path = path or EVENT_LOG_PATH
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def emit(self, name: str, payload: Optional[dict] = None, source: str = "scheduler") -> dict:
        event = {"ts_utc": self._clock().isoformat(), "name": name,
                 "source": source, "payload": payload or {}}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, default=str) + "\n")
        return event

    def read(self, name: Optional[str] = None, limit: int = 1000) -> list[dict]:
        if not self._path.exists():
            return []
        out: list[dict] = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if name is None or ev.get("name") == name:
                    out.append(ev)
        return out[-limit:]
