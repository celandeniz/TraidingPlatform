"""Run ONE backtest from a strategy key, on intraday or daily bars.

Extracted so /api/backtest (and tests) share one code path. The strategy map
covers the bar-agnostic signal strategies; orb_breakout/gap_go are intraday-
session strategies and are intentionally excluded from this generic runner.
"""
from __future__ import annotations

from .engine import CostModel, ExitParams, run_backtest

DAILY_TIMEFRAMES = {"1d", "1day", "daily"}


def _strategy_fns() -> dict:
    from ..strategy.atr_trend import generate as atr_g
    from ..strategy.donchian_breakout import generate as donch
    from ..strategy.ema_momentum import generate as ema
    from ..strategy.keltner_breakout import generate as kelt
    from ..strategy.macd_cross import generate as macd_g
    from ..strategy.rsi_reversion import generate as rsi_g
    from ..strategy.spike_fade import generate as spike
    from ..strategy.vwap_reversion import generate as vwap_g

    return {
        "spike_fade": lambda df: spike(df, zscore_window=20, lookback_k=2, z_entry=2.0),
        "ema_momentum": lambda df: ema(df, fast=12, slow=26),
        "donchian": lambda df: donch(df, channel=20),
        "rsi_reversion": lambda df: rsi_g(df, period=14),
        "macd_cross": lambda df: macd_g(df, fast=12, slow=26),
        "vwap_reversion": lambda df: vwap_g(df, band_pct=1.0),
        "keltner_breakout": lambda df: kelt(df, period=20, mult=2.0),
        "atr_trend": lambda df: atr_g(df, period=20, k=1.5),
    }


def available_strategies() -> list:
    return list(_strategy_fns().keys())


def run_one(df, strategy: str, *, take_profit_pct: float = 2.0,
            stop_loss_pct: float = 1.5, scenario: str = ""):
    """Backtest one strategy on df. Raises KeyError for an unknown strategy."""
    fns = _strategy_fns()
    if strategy not in fns:
        raise KeyError(f"unknown strategy '{strategy}'; have {sorted(fns)}")
    return run_backtest(
        df, fns[strategy],
        exits=ExitParams(take_profit_pct, stop_loss_pct, 0.8, 90, True),
        costs=CostModel(1.0, 2.0), warmup=35, scenario=scenario)


def load_bars(symbol: str, timeframe: str, bars: int, provider):
    """Daily timeframes come from the (working) DailyBarCache; everything else
    from the live intraday provider."""
    if timeframe.lower() in DAILY_TIMEFRAMES:
        from ..data.daily_cache import DailyBarCache
        from ..settings import BACKEND_DIR

        cache = DailyBarCache(BACKEND_DIR / "store" / "daily_cache")
        cache.ensure([symbol.upper()], min_years=max(2, bars // 252))
        df = cache.get(symbol.upper())
        return df.tail(bars) if df is not None else df
    return provider.get_recent_bars(symbol.upper(), timeframe, bars)
