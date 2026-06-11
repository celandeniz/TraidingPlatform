"""Event-driven backtest engine — NO LOOKAHEAD, realistic fills.

Core anti-lookahead contract (the thing that makes a backtest honest):
  * A signal is computed using ONLY bars[0 .. i] (data known at the close of bar i).
  * The resulting order fills at the OPEN of bar i+1 — never the same bar's close,
    never a future bar. You cannot trade on information you didn't have yet.
  * Exits are evaluated each subsequent bar against that bar's OHLC, again using
    only past+current data; the exit fill is modeled at the level that triggered
    it (stop/TP price) or the next open, whichever is conservative.

Costs are charged on every fill: commission (bps) + slippage (bps), applied
adversely (buys fill higher, sells fill lower). Supports long AND short.

This is a single-instrument, one-position-at-a-time backtest (matches the live
PositionManager's "at most one position per symbol" rule). Pure: give it a
DataFrame + a signal function + params, get a BacktestResult. No network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pandas as pd

# A signal function: (window_df) -> {"buy": bool, "sell": bool, ...}
# window_df is bars[0..i] inclusive; it must NOT see anything past row i.
SignalFn = Callable[[pd.DataFrame], dict]


@dataclass
class CostModel:
    commission_bps: float = 1.0   # per side, basis points of notional
    slippage_bps: float = 2.0     # adverse, per fill

    @classmethod
    def from_fill_config(cls, cfg) -> "CostModel":
        """Build a CostModel from a FillModelConfig so the backtest charges the
        SAME per-fill cost the live/mock FillModel does (half-spread + base
        slippage as the 'slippage' term, commission as commission). Lets one set
        of assumptions drive both backtest and execution. Order-book impact /
        partial fills don't map onto the single-position fraction backtest, so
        they're intentionally excluded here."""
        return cls(commission_bps=cfg.commission_bps,
                   slippage_bps=cfg.spread_bps / 2.0 + cfg.base_slippage_bps)


@dataclass
class ExitParams:
    take_profit_pct: float = 1.5
    stop_loss_pct: float = 1.0
    trailing_stop_pct: Optional[float] = None
    time_stop_bars: Optional[int] = None
    allow_short: bool = True


@dataclass
class Trade:
    side: str            # "long" | "short"
    entry_idx: int
    exit_idx: int
    entry_px: float
    exit_px: float
    bars_held: int
    reason: str
    ret_pct: float       # net of costs, signed for the position


@dataclass
class BacktestResult:
    scenario: str = ""
    n_trades: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0    # compounded equity return over the window
    profit_factor: float = 0.0       # gross win / gross loss
    avg_trade_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0              # per-trade Sharpe (mean/std), not annualized
    buy_hold_pct: float = 0.0       # benchmark over the same window
    excess_vs_buy_hold: float = 0.0
    exposure_pct: float = 0.0       # fraction of bars in a position
    # statistical significance of the per-trade returns (guard against noise)
    p_value: float = 1.0
    t_stat: float = 0.0
    ci_low_pct: float = 0.0         # bootstrap 95% CI on mean per-trade return
    ci_high_pct: float = 0.0
    significant: bool = False       # p<0.05 AND n>=20 AND CI excludes 0
    significance_label: str = ""
    trades: list = field(default_factory=list)
    error: str = ""


def _apply_cost(px: float, side_is_buy: bool, costs: CostModel) -> float:
    """Adverse fill: buys pay up, sells receive less."""
    bps = (costs.commission_bps + costs.slippage_bps) / 10000.0
    return px * (1 + bps) if side_is_buy else px * (1 - bps)


def run_backtest(
    df: pd.DataFrame,
    signal_fn: SignalFn,
    *,
    exits: ExitParams,
    costs: CostModel = CostModel(),
    warmup: int = 30,
    scenario: str = "",
) -> BacktestResult:
    """Run one backtest. df: OHLCV, oldest..newest, tz-aware index.

    signal_fn receives df.iloc[:i+1] (no future data) and returns buy/sell flags.
    """
    n = len(df)
    if n < warmup + 5:
        return BacktestResult(scenario=scenario, error="insufficient data")

    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()

    trades: list[Trade] = []
    equity = 1.0
    equity_curve = [1.0]
    peak = 1.0
    max_dd = 0.0
    bars_in_pos = 0

    pos = None  # dict: side, entry_idx, entry_px, high_water
    i = warmup
    while i < n - 1:  # need i+1 to exist for next-bar-open fill
        # ----- manage an open position on bar i (uses only bar i OHLC) -----
        if pos is not None:
            bars_in_pos += 1
            side = pos["side"]
            entry = pos["entry_px"]
            sign = 1.0 if side == "long" else -1.0
            # update trailing extreme
            pos["high_water"] = max(pos["high_water"], high[i]) if side == "long" \
                else min(pos["high_water"], low[i])

            exit_px = None
            reason = None
            # Stop / take-profit are checked against this bar's range. If both the
            # stop and TP are inside the bar, assume the STOP hit first (conservative).
            if side == "long":
                stop_px = entry * (1 - pos["stop_loss_pct"] / 100.0)
                tp_px = entry * (1 + pos["take_profit_pct"] / 100.0)
                if low[i] <= stop_px:
                    exit_px, reason = stop_px, "stop_loss"
                elif high[i] >= tp_px:
                    exit_px, reason = tp_px, "take_profit"
                elif exits.trailing_stop_pct is not None:
                    trail = pos["high_water"] * (1 - exits.trailing_stop_pct / 100.0)
                    if low[i] <= trail:
                        exit_px, reason = trail, "trailing_stop"
            else:  # short
                stop_px = entry * (1 + pos["stop_loss_pct"] / 100.0)
                tp_px = entry * (1 - pos["take_profit_pct"] / 100.0)
                if high[i] >= stop_px:
                    exit_px, reason = stop_px, "stop_loss"
                elif low[i] <= tp_px:
                    exit_px, reason = tp_px, "take_profit"
                elif exits.trailing_stop_pct is not None:
                    trail = pos["high_water"] * (1 + exits.trailing_stop_pct / 100.0)
                    if high[i] >= trail:
                        exit_px, reason = trail, "trailing_stop"

            held = i - pos["entry_idx"]
            if exit_px is None and pos["time_stop_bars"] is not None and held >= pos["time_stop_bars"]:
                exit_px, reason = close[i], "time_stop"  # exit at this close

            if exit_px is not None:
                fill = _apply_cost(exit_px, side_is_buy=(side == "short"), costs=costs)
                gross = sign * (fill / entry - 1.0)
                equity *= (1 + gross)
                trades.append(Trade(side, pos["entry_idx"], i, entry, fill, held,
                                    reason, gross * 100.0))
                pos = None
                equity_curve.append(equity)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak)
                i += 1
                continue

        # ----- look for a new entry signal at the close of bar i -----
        if pos is None:
            window = df.iloc[: i + 1]  # bars 0..i only — no future leak
            sig = signal_fn(window)
            want = None
            if sig.get("buy"):
                want = "long"
            elif sig.get("sell") and exits.allow_short:
                want = "short"
            if want is not None:
                # FILL AT NEXT BAR'S OPEN (i+1) — the key anti-lookahead rule.
                raw_entry = open_[i + 1]
                entry_px = _apply_cost(raw_entry, side_is_buy=(want == "long"), costs=costs)
                pos = {"side": want, "entry_idx": i + 1, "entry_px": entry_px,
                       "high_water": entry_px,
                       # per-signal exit overrides; fall back to global ExitParams
                       "stop_loss_pct": sig.get("stop_loss_pct", exits.stop_loss_pct),
                       "take_profit_pct": sig.get("take_profit_pct", exits.take_profit_pct),
                       "time_stop_bars": sig.get("time_stop_bars", exits.time_stop_bars)}
                i += 1
                continue
        i += 1

    # close any residual position at the last bar's close (marked, conservative)
    if pos is not None:
        side = pos["side"]; entry = pos["entry_px"]; sign = 1.0 if side == "long" else -1.0
        fill = _apply_cost(close[-1], side_is_buy=(side == "short"), costs=costs)
        gross = sign * (fill / entry - 1.0)
        equity *= (1 + gross)
        trades.append(Trade(side, pos["entry_idx"], n - 1, entry, fill,
                            n - 1 - pos["entry_idx"], "eod_close", gross * 100.0))
        equity_curve.append(equity)

    return _summarize(trades, equity, equity_curve, close, n, bars_in_pos, scenario)


def _summarize(trades, equity, equity_curve, close, n, bars_in_pos, scenario) -> BacktestResult:
    if not trades:
        bh = (close[-1] / close[0] - 1.0) * 100.0
        return BacktestResult(scenario=scenario, n_trades=0, buy_hold_pct=bh,
                              total_return_pct=0.0, excess_vs_buy_hold=-bh)
    rets = [t.ret_pct for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = var ** 0.5
    sharpe = (mean / std) if std > 0 else 0.0
    peak = 1.0; max_dd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    total_ret = (equity - 1.0) * 100.0
    bh = (close[-1] / close[0] - 1.0) * 100.0
    from .stats import significance
    sg = significance(rets)
    return BacktestResult(
        scenario=scenario, n_trades=len(trades),
        win_rate=len(wins) / len(trades) * 100.0,
        total_return_pct=total_ret,
        profit_factor=round(pf, 3) if pf != float("inf") else 999.0,
        avg_trade_pct=mean, max_drawdown_pct=max_dd * 100.0,
        sharpe=round(sharpe, 3), buy_hold_pct=bh,
        excess_vs_buy_hold=total_ret - bh,
        exposure_pct=bars_in_pos / n * 100.0,
        p_value=sg.p_value, t_stat=sg.t_stat, ci_low_pct=sg.ci_low_pct,
        ci_high_pct=sg.ci_high_pct, significant=sg.significant,
        significance_label=sg.label,
        trades=trades,
    )
