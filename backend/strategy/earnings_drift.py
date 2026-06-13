"""Post-Earnings-Announcement Drift (PEAD) on daily bars.

If the LAST bar is an earnings reaction day (its date within match_days of a
known earnings date) AND it gapped >= gap_min_pct over the prior close AND
volume >= vol_mult x its 20-day average, go long; hold `hold_days` with a
stop_pct stop and no profit target (per-signal overrides, take_profit huge).
Short side (negative surprise) behind allow_short, default off.

match_days is measured in BUSINESS days (Fri AMC -> Mon reaction = 1).

generate() is pure: earnings_dates are passed in. The tournament wires the
EarningsCalendar (backend/data/earnings.py) at orchestration time — this is a
daily-bar tournament/swing strategy, not a live 1m runner strategy, so it is
deliberately NOT in SIGNAL_STRATEGIES.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VOL_AVG_DAYS = 20
NO_TP = 1000.0   # effectively "no take-profit" via the per-signal override


def generate(
    df: pd.DataFrame,
    *,
    earnings_dates: list,
    gap_min_pct: float = 5.0,
    vol_mult: float = 1.5,
    hold_days: int = 20,
    stop_pct: float = 10.0,
    match_days: int = 1,
    allow_short: bool = False,
) -> dict:
    no = {"buy": False, "sell": False}
    if len(df) < VOL_AVG_DAYS + 2 or not earnings_dates:
        return no
    last = df.index[-1]
    last_d = last.date()

    def _bus_diff(e) -> int:
        ed = pd.Timestamp(e).normalize().date()
        # PEAD is a reaction AFTER the announcement: a future earnings date must
        # never match (that would trade the gap before the event = lookahead).
        if ed > last_d:
            return 10 ** 9
        return int(np.busday_count(ed, last_d))

    if not any(_bus_diff(e) <= match_days for e in earnings_dates):
        return no
    prev_close = float(df["close"].iloc[-2])
    open_ = float(df["open"].iloc[-1])
    gap_pct = (open_ / prev_close - 1.0) * 100.0
    avg_vol = float(df["volume"].iloc[-VOL_AVG_DAYS - 1:-1].mean())
    vol_ok = avg_vol > 0 and float(df["volume"].iloc[-1]) >= vol_mult * avg_vol

    buy = vol_ok and gap_pct >= gap_min_pct
    sell = allow_short and vol_ok and gap_pct <= -gap_min_pct
    if not (buy or sell):
        return no
    return {"buy": bool(buy), "sell": bool(sell),
            "stop_loss_pct": stop_pct, "take_profit_pct": NO_TP,
            "time_stop_bars": hold_days, "gap_pct": round(gap_pct, 3)}
