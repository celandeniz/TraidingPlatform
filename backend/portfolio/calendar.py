"""Market calendars: equity (US/NYSE regular hours) vs crypto (always open).

Used by the position manager to decide end-of-day-flat (equity only) and by the
risk manager to gate equity entries outside the session. Pure given the `now`
passed in (tz-aware UTC).
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


class EquityCalendar:
    """US regular session 09:30–16:00 ET, Mon–Fri (holidays not modeled here)."""

    def is_open(self, now: datetime) -> bool:
        et = now.astimezone(ET)
        if et.weekday() >= 5:  # Sat/Sun
            return False
        return _OPEN <= et.time() < _CLOSE

    def is_closing_within(self, now: datetime, minutes: int) -> bool:
        et = now.astimezone(ET)
        if et.weekday() >= 5 or not (_OPEN <= et.time() < _CLOSE):
            return False
        close_dt = et.replace(hour=_CLOSE.hour, minute=_CLOSE.minute, second=0, microsecond=0)
        return 0 <= (close_dt - et).total_seconds() / 60.0 <= minutes


class CryptoCalendar:
    """24/7 — always open, never closing."""

    def is_open(self, now: datetime) -> bool:
        return True

    def is_closing_within(self, now: datetime, minutes: int) -> bool:
        return False


def calendar_for(asset_class: str):
    return CryptoCalendar() if asset_class == "crypto" else EquityCalendar()
