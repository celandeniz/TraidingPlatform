"""Adapter: load a validated candidate and run it through the backtest engine.

A generated strategy conforms to the RUNNER contract — evaluate(ctx) ->
StrategySignal (backend/strategy/base.py). The engine wants signal_fn(window) ->
{"buy"/"sell"}. make_signal_fn bridges the two so backtest behavior matches the
eventual paper behavior.

Code is exec'd in a stripped namespace (no imports, safe builtins, only pandas +
indicators + the BarContext/StrategySignal contract injected). In production this
runs inside the subprocess sandbox; tests call evaluate_candidate directly with
trusted source.
"""
from __future__ import annotations

import builtins as _builtins

_SAFE_BUILTIN_NAMES = (
    "len", "min", "max", "abs", "range", "sum", "sorted", "enumerate", "zip",
    "float", "int", "bool", "round", "list", "dict", "tuple", "set", "map",
    "filter", "any", "all", "str", "print", "isinstance", "Exception",
    "ValueError", "TypeError", "ZeroDivisionError", "KeyError", "IndexError",
)
SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _SAFE_BUILTIN_NAMES}
# __build_class__ is required for the `class` statement to execute; __name__ is
# referenced by class bodies. Neither is a sandbox-escape vector on its own.
SAFE_BUILTINS["__build_class__"] = _builtins.__build_class__
SAFE_BUILTINS["__name__"] = "candidate"


def load_strategy_class(source: str, class_name: str):
    """Compile+exec the candidate in a restricted namespace; return the class."""
    import pandas as pd

    from ..strategy import base, indicators

    ns = {
        "__builtins__": SAFE_BUILTINS,
        "pd": pd, "pandas": pd, "indicators": indicators,
        "BarContext": base.BarContext, "StrategySignal": base.StrategySignal,
    }
    exec(compile(source, "<candidate>", "exec"), ns)  # noqa: S102 - sandboxed namespace
    cls = ns.get(class_name)
    if cls is None:
        raise ValueError(f"class {class_name} not defined by source")
    return cls


def make_signal_fn(strategy, config: dict):
    """Wrap a strategy instance's evaluate(ctx) into engine signal_fn(window)."""
    from ..strategy.base import BarContext

    def fn(window) -> dict:
        ctx = BarContext(symbol="GEN", window=window, config=config,
                         get_bars=lambda tf, n: window.tail(n))
        try:
            sig = strategy.evaluate(ctx)
        except Exception:  # noqa: BLE001 - a misbehaving bar => no signal
            return {}
        if sig is None or getattr(sig, "side", None) is None:
            return {}
        return {"buy": sig.side == "buy", "sell": sig.side == "sell"}

    return fn


def _metrics(res) -> dict:
    return {
        "n_trades": res.n_trades,
        "win_rate": res.win_rate,
        "total_return_pct": res.total_return_pct,
        "profit_factor": res.profit_factor,
        "max_drawdown_pct": res.max_drawdown_pct,
        "sharpe": res.sharpe,
        "significant": res.significant,
        "p_value": res.p_value,
        "exposure_pct": res.exposure_pct,
        "error": res.error,
    }


def evaluate_candidate(source: str, class_name: str, df, *, config: dict,
                       exits=None, warmup: int = 35, oos_frac: float = 0.3) -> dict:
    """Backtest a candidate on `df`; return ranker-ready metrics incl. oos_sharpe.

    oos_sharpe = per-trade Sharpe on the out-of-sample tail (guards overfit), and
    is what rank_reports() sorts on.
    """
    from ..backtest.engine import ExitParams, run_backtest

    exits = exits or ExitParams(2.0, 1.5, 0.8, 90, True)
    cls = load_strategy_class(source, class_name)
    strategy = cls()
    fn = make_signal_fn(strategy, config)

    full = run_backtest(df, fn, exits=exits, warmup=warmup, scenario="full")
    metrics = _metrics(full)

    # Out-of-sample tail for the ranking key.
    split = int(len(df) * (1 - oos_frac))
    oos_sharpe = 0.0
    if len(df) - split > warmup + 5:
        # fresh instance: no state leaks across the split
        oos = run_backtest(df.iloc[split:], make_signal_fn(cls(), config),
                           exits=exits, warmup=warmup, scenario="oos")
        oos_sharpe = oos.sharpe if not oos.error else 0.0
    metrics["oos_sharpe"] = oos_sharpe
    return metrics
