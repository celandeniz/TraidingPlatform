"""Gap-and-Go — momentum continuation on large opening gaps.

Long setup: today's open gaps >= gap_min_pct above the prior session close, price
has NOT filled the gap (never traded back through the prior close), the last bar
holds above session VWAP and is the FIRST close above the opening
`confirm_minutes` high. Stop at VWAP, ~2R target, hard exit 15:55 ET via
per-signal overrides. Mirrored short side behind allow_short (default off).

Prior session close comes from the 1m window itself (last bar of the most recent
earlier session) — works identically live and in backtest.

Live-window caveat (same as orb_breakout): the today-session must include the
real 09:30 ET bar; a rolling window that starts mid-day returns no signal rather
than fabricating an open print. A window without any prior session also returns
no signal.
"""
from __future__ import annotations

import pandas as pd

from .base import BarContext, StrategySignal
from .indicators import vwap

SESSION_TZ = "America/New_York"
OPEN = "09:30"
SESSION_END = "16:00"
LAST_ENTRY = "15:30"
HARD_EXIT = "15:55"


def generate(
    df: pd.DataFrame,
    *,
    gap_min_pct: float = 2.0,
    confirm_minutes: int = 5,
    risk_reward: float = 2.0,
    allow_short: bool = False,
) -> dict:
    """Evaluate Gap-and-Go on the LAST closed 1m bar of df. Needs OHLCV, tz-aware index.

    The today-session must include the real 09:30 ET bar. A rolling window that
    starts mid-day returns no signal rather than fabricating an open print.
    A window without any prior session also returns no signal.
    """
    no = {"buy": False, "sell": False}
    if len(df) < confirm_minutes + 2:
        return no
    et = df.copy()
    et.index = et.index.tz_convert(SESSION_TZ)
    last_ts = et.index[-1]
    if last_ts.time() > pd.Timestamp(f"2000-01-01 {LAST_ENTRY}").time():
        return no
    today = et[et.index.date == last_ts.date()].between_time(OPEN, SESSION_END)
    prior = et[et.index.date < last_ts.date()]
    if prior.empty or len(today) < confirm_minutes + 1:
        return no
    # anchor: the real 09:30 bar must be present (rolling-window safety)
    if today.index[0].time() != pd.Timestamp(f"2000-01-01 {OPEN}").time():
        return no
    prev_close = float(prior["close"].iloc[-1])
    open_print = float(today["open"].iloc[0])
    gap_pct = (open_print / prev_close - 1.0) * 100.0

    v = float(vwap(today).iloc[-1])
    close = float(today["close"].iloc[-1])
    prev_bar_close = float(today["close"].iloc[-2])
    hi_n = float(today["high"].iloc[:confirm_minutes].max())
    lo_n = float(today["low"].iloc[:confirm_minutes].min())

    buy = sell = False
    if gap_pct >= gap_min_pct:
        filled = bool((today["low"] <= prev_close).any())
        buy = (not filled) and close > v and prev_bar_close <= hi_n and close > hi_n
    elif allow_short and gap_pct <= -gap_min_pct:
        filled = bool((today["high"] >= prev_close).any())
        sell = (not filled) and close < v and prev_bar_close >= lo_n and close < lo_n
    if not (buy or sell):
        return no

    stop_pct = abs(close - v) / close * 100.0
    if stop_pct <= 0.01:                       # too close to VWAP — no edge to risk
        return no
    bars_to_exit = max(1, int((pd.Timestamp(f"{last_ts.date()} {HARD_EXIT}",
                                            tz=SESSION_TZ) - last_ts).total_seconds() // 60))
    return {
        "buy": buy, "sell": sell,
        "stop_loss_pct": round(stop_pct, 4),
        "take_profit_pct": round(risk_reward * stop_pct, 4),
        "time_stop_bars": bars_to_exit,
        "gap_pct": round(gap_pct, 3), "vwap": round(v, 4),
    }


class GapGoStrategy:
    name = "gap_go"

    def evaluate(self, ctx: BarContext) -> StrategySignal:
        p = ctx.config.get("gap_go", {})
        res = generate(
            ctx.window,
            gap_min_pct=p.get("gap_min_pct", 2.0),
            confirm_minutes=p.get("confirm_minutes", 5),
            risk_reward=p.get("risk_reward", 2.0),
            allow_short=p.get("allow_short", False),
        )
        side = "buy" if res.get("buy") else "sell" if res.get("sell") else None
        return StrategySignal(side=side, strength=abs(res.get("gap_pct", 0.0)) if side else 0.0,
                              meta=res)
