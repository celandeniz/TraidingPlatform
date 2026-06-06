"""Scheduler primitives — pure, deterministic (clock injected)."""
from datetime import datetime, time, timedelta, timezone

from backend.scheduler.core import EventLog, Heartbeat, Schedule

UTC = timezone.utc


def test_interval_next_fire_steps_forward():
    anchor = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    s = Schedule("tick", "interval", every_seconds=60, anchor=anchor)
    # before anchor -> fires at anchor
    assert s.next_fire(datetime(2023, 12, 31, 23, 0, tzinfo=UTC)) == anchor
    # 90s in -> next 60s boundary is at +120s
    nf = s.next_fire(anchor + timedelta(seconds=90))
    assert nf == anchor + timedelta(seconds=120)


def test_once_fires_only_in_future():
    at = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    s = Schedule("deploy", "once", at=at)
    assert s.next_fire(datetime(2024, 5, 1, tzinfo=UTC)) == at
    assert s.next_fire(datetime(2024, 7, 1, tzinfo=UTC)) is None


def test_heartbeat_respects_interval_and_dedup():
    hb = Heartbeat(interval_seconds=60, dedup_seconds=30)
    t0 = datetime(2024, 1, 1, 14, 0, tzinfo=UTC)
    assert hb.tick(t0) is True
    assert hb.tick(t0 + timedelta(seconds=30)) is False  # within interval
    assert hb.tick(t0 + timedelta(seconds=61)) is True


def test_heartbeat_active_hours_window():
    hb = Heartbeat(interval_seconds=1, active_start=time(13, 30), active_end=time(20, 0))
    assert hb.should_tick(datetime(2024, 1, 1, 12, 0, tzinfo=UTC)) is False  # before open
    assert hb.should_tick(datetime(2024, 1, 1, 14, 0, tzinfo=UTC)) is True   # in window
    assert hb.should_tick(datetime(2024, 1, 1, 21, 0, tzinfo=UTC)) is False  # after close


def test_heartbeat_active_hours_wraps_midnight():
    hb = Heartbeat(interval_seconds=1, active_start=time(22, 0), active_end=time(4, 0))
    assert hb.should_tick(datetime(2024, 1, 1, 23, 0, tzinfo=UTC)) is True
    assert hb.should_tick(datetime(2024, 1, 1, 2, 0, tzinfo=UTC)) is True
    assert hb.should_tick(datetime(2024, 1, 1, 12, 0, tzinfo=UTC)) is False


def test_event_log_emit_and_filter(tmp_path):
    log = EventLog(path=tmp_path / "events.jsonl",
                   clock=lambda: datetime(2024, 1, 1, tzinfo=UTC))
    log.emit("snapshot", {"equity": 100})
    log.emit("news_fetch", {"n": 3})
    log.emit("snapshot", {"equity": 101})
    assert len(log.read()) == 3
    snaps = log.read(name="snapshot")
    assert len(snaps) == 2 and snaps[-1]["payload"]["equity"] == 101
