"""Automation layer: cron/interval/one-shot schedules, a heartbeat, and an
append-only event log — the OpenAlice scheduling concept in Python.

Pure scheduling math (next-fire, active-hours, dedup) with no background threads
here; the runner/web layer drives the clock. Clean-room reimplementation.
"""
from .core import EventLog, Heartbeat, Schedule

__all__ = ["Schedule", "Heartbeat", "EventLog"]
