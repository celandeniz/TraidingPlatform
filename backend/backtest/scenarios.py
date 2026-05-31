"""Generate ~250 backtest scenarios: strategy x params x symbol x timeframe.

Each scenario pairs a signal function (bound params) with an exit config, run on
one (symbol, timeframe) dataset. The grid is intentionally broad so we can see
which configurations are robustly positive net of costs — and which lose (we
report both honestly).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

import pandas as pd

from .engine import ExitParams
from ..strategy.donchian_breakout import generate as donchian_gen
from ..strategy.ema_momentum import generate as ema_gen
from ..strategy.spike_fade import generate as spike_gen


@dataclass
class Scenario:
    name: str
    symbol: str
    timeframe: str
    signal_fn: Callable[[pd.DataFrame], dict]
    exits: ExitParams


def _spike(zw, ze, k):
    def fn(df):
        return spike_gen(df, zscore_window=zw, lookback_k=k, z_entry=ze,
                         rsi_period=14, rsi_oversold=30, rsi_overbought=70)
    return fn


def _ema(fast, slow):
    def fn(df):
        return ema_gen(df, fast=fast, slow=slow)
    return fn


def _donch(ch):
    def fn(df):
        return donchian_gen(df, channel=ch)
    return fn


def build_scenarios(symbols, timeframes, *, target=250) -> list[Scenario]:
    """Build a deterministic grid of scenarios up to ~target count."""
    scenarios: list[Scenario] = []

    # Strategy parameter grids (mean-reversion, momentum, breakout).
    spike_grid = [(zw, ze, k) for zw in (15, 20) for ze in (1.5, 2.0, 2.5) for k in (2, 3)]
    ema_grid = [(f, s) for f, s in [(8, 21), (12, 26), (9, 30), (5, 20)]]
    donch_grid = [(ch,) for ch in (10, 20, 30)]

    # Exit profiles (tp, sl, trail, time_stop_bars).
    exit_grid = [
        ExitParams(1.0, 0.8, None, 30, True),
        ExitParams(1.5, 1.0, 0.8, 60, True),
        ExitParams(2.0, 1.5, None, 90, True),
    ]

    strat_specs = (
        [("spike_fade", _spike(zw, ze, k), f"sf_z{ze}_w{zw}_k{k}") for (zw, ze, k) in spike_grid]
        + [("ema_momentum", _ema(f, s), f"ema_{f}_{s}") for (f, s) in ema_grid]
        + [("donchian", _donch(ch), f"don_{ch}") for (ch,) in donch_grid]
    )

    for (sym, tf, (strat, fn, label), ex) in product(symbols, timeframes, strat_specs, exit_grid):
        name = f"{sym}|{tf}|{label}|tp{ex.take_profit_pct}sl{ex.stop_loss_pct}"
        scenarios.append(Scenario(name, sym, tf, fn, ex))
        if len(scenarios) >= target:
            return scenarios
    return scenarios
