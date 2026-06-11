"""Opening Range Breakout (ORB) — classic US-equity intraday strategy.

Opening range = high/low of the first `range_minutes` after 09:30 ET. Long on the
FIRST 1m close above the range high (short below range low). Stop at the far side
of the range, take-profit at `risk_reward` x R, hard time-exit at 15:55 ET — all
emitted as per-signal exit overrides (engine.py).

Filters (each auto-skipped when the window lacks history to compute it):
  * relative volume: today's cumulative volume >= min_rel_volume x the average
    cumulative volume at the same minute over prior sessions in the window.
  * range width >= min_range_atr x daily ATR(14) resampled from prior sessions.

Live-window limitation: The live runner's rolling 1m window may not include
prior sessions; both filters auto-skip then (they bind in backtests/tournament
runs which use full history). The range anchor requires the 09:30 bar to be in
the window — with a 240-bar window ORB therefore only signals during the morning,
by design.

Pure logic in generate(df); OrbBreakoutStrategy adapts to SignalStrategy.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal

SESSION_TZ = "America/New_York"
OPEN = "09:30"
SESSION_END = "16:00"
LAST_ENTRY = "15:30"   # no fresh entries after this
HARD_EXIT = "15:55"


def _et(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.tz_convert(SESSION_TZ)
    return out


def generate(
    df: pd.DataFrame,
    *,
    range_minutes: int = 15,
    risk_reward: float = 2.0,
    min_rel_volume: float = 1.5,
    min_range_atr: float = 0.3,
) -> dict:
    """Evaluate ORB on the LAST closed 1m bar of df. Needs OHLCV, tz-aware index.

    The opening range is anchored to the REAL 09:30 ET bar. If the 09:30 bar is
    not present in the window (e.g. live runner with a 240-bar rolling window that
    has scrolled past the open) the function returns no-signal immediately.
    """
    no = {"buy": False, "sell": False}
    if len(df) < range_minutes + 1:
        return no
    et = _et(df)
    last_ts = et.index[-1]
    day = et[et.index.date == last_ts.date()]
    session = day.between_time(OPEN, SESSION_END)
    if len(session) < range_minutes + 1:
        return no                       # range still forming (or no session data)
    if last_ts.time() > pd.Timestamp(f"2000-01-01 {LAST_ENTRY}").time():
        return no                       # too late in the day to enter

    # --- anchor: session must start at the real 09:30 bar ---
    open_time = pd.Timestamp("2000-01-01 09:30").time()
    if session.index[0].time() != open_time:
        return no                       # rolling window has scrolled past the open

    # --- select the range by TIMESTAMP, not position ---
    range_end_ts = pd.Timestamp(f"2000-01-01 09:30") + pd.Timedelta(minutes=range_minutes - 1)
    range_end_time = range_end_ts.time()   # e.g. 09:44 for range_minutes=15
    rng = session.between_time(OPEN, str(range_end_time)[:5])

    # Require full range: >= range_minutes bars AND at least one bar strictly after it
    if len(rng) < range_minutes:
        return no

    range_hi = float(rng["high"].max())
    range_lo = float(rng["low"].min())
    close = float(session["close"].iloc[-1])
    prev_close = float(session["close"].iloc[-2])

    # FIRST-cross only: previous bar inside the range, this bar's close outside.
    buy = prev_close <= range_hi and close > range_hi
    sell = prev_close >= range_lo and close < range_lo
    if not (buy or sell):
        return no

    prior = et[et.index.date < last_ts.date()].between_time(OPEN, SESSION_END)
    prior_days = sorted(set(prior.index.date))

    # --- relative-volume filter (needs >= 3 prior sessions) ---
    if min_rel_volume > 0 and len(prior_days) >= 3:
        cum_today = float(session["volume"].sum())
        t = last_ts.time()
        prior_cums = []
        for d in prior_days:
            ds = prior[prior.index.date == d]
            ds = ds[ds.index.time <= t]
            if len(ds):
                prior_cums.append(float(ds["volume"].sum()))
        if prior_cums:
            avg = sum(prior_cums) / len(prior_cums)
            if avg > 0 and cum_today < min_rel_volume * avg:
                return no

    # --- range-width vs daily ATR filter (needs >= 15 prior sessions) ---
    if min_range_atr > 0 and len(prior_days) >= 15:
        daily = prior.groupby(prior.index.date).agg(
            high=("high", "max"), low=("low", "min"), close=("close", "last"))
        prev_c = daily["close"].shift(1)
        tr = pd.concat([daily["high"] - daily["low"],
                        (daily["high"] - prev_c).abs(),
                        (daily["low"] - prev_c).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        if pd.notna(atr) and (range_hi - range_lo) < min_range_atr * atr:
            return no

    # --- per-signal exits (engine overrides) ---
    if buy:
        stop_pct = (close - range_lo) / close * 100.0
    else:
        stop_pct = (range_hi - close) / close * 100.0
    if stop_pct <= 0:
        return no
    bars_to_exit = max(1, int((pd.Timestamp(f"{last_ts.date()} {HARD_EXIT}",
                                            tz=SESSION_TZ) - last_ts).total_seconds() // 60))
    return {
        "buy": bool(buy), "sell": bool(sell),
        "stop_loss_pct": round(stop_pct, 4),
        "take_profit_pct": round(risk_reward * stop_pct, 4),
        "time_stop_bars": bars_to_exit,
        "range_hi": range_hi, "range_lo": range_lo,
    }


class OrbBreakoutStrategy:
    """ORB strategy adapter for the SignalStrategy protocol.

    The live runner's rolling 1m window may not include prior sessions; both
    filters auto-skip then (they bind in backtests/tournament runs which use
    full history). The range anchor requires the 09:30 bar to be in the
    window — with a 240-bar window ORB therefore only signals during the
    morning, by design.
    """

    name = "orb_breakout"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("orb_breakout", {})
        res = generate(
            ctx.window,
            range_minutes=p.get("range_minutes", 15),
            risk_reward=p.get("risk_reward", 2.0),
            min_rel_volume=p.get("min_rel_volume", 1.5),
            min_range_atr=p.get("min_range_atr", 0.3),
        )
        side = "buy" if res.get("buy") else "sell" if res.get("sell") else None
        return StrategySignal(side=side, strength=1.0 if side else 0.0, meta=res)
