"""1-month backtest over all 7 Magnificent-7 symbols at 5m — list ALL 250 scenarios.

Trims each symbol's 5m series to the last `days` (default 30) so every test runs
on the same ~1-month window. No lookahead, next-bar-open fills, costs in (see
engine.py). Writes the full table to logs/backtest_month_<date>.csv and prints
every scenario (not just top/worst).

    .venv/bin/python -m backend.backtest.run_month [n_scenarios] [days]
"""
from __future__ import annotations

import sys

import pandas as pd

from ..data.alpaca_provider import AlpacaProvider
from ..settings import REPO_DIR, get_config, get_settings
from .engine import CostModel, run_backtest
from .scenarios import build_scenarios


def fetch_month(provider, symbols, days):
    """5m bars per symbol, trimmed to the last `days`."""
    data = {}
    for sym in symbols:
        try:
            df = provider.get_recent_bars(sym, "5m", 3000)
            if len(df) > 1:
                cut = df.index[-1] - pd.Timedelta(days=days)
                df = df[df.index >= cut]
            data[sym] = df
            span = (df.index[-1] - df.index[0]) if len(df) > 1 else "n/a"
            print(f"[data] {sym} 5m: {len(df)} bars, {span}")
        except Exception as exc:  # noqa: BLE001
            data[sym] = None
            print(f"[data] {sym} 5m: FAILED ({exc})")
    return data


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    s = get_settings(); cfg = get_config()
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    symbols = cfg["universe"]                 # all 7 M7
    costs = CostModel(commission_bps=1.0, slippage_bps=2.0)

    data = fetch_month(provider, symbols, days)
    # 5m only -> the scenario grid distributes its param combos across the 7 symbols.
    scenarios = build_scenarios(symbols, ["5m"], target=n)
    print(f"\n[grid] {len(scenarios)} scenarios | 7 M7 symbols | 5m | last {days}d | "
          f"no lookahead | next-bar-open | {costs.commission_bps + costs.slippage_bps:.0f}bps\n")

    rows = []
    for sc in scenarios:
        df = data.get(sc.symbol)
        if df is None or len(df) < 60:
            continue
        r = run_backtest(df, sc.signal_fn, exits=sc.exits, costs=costs, warmup=35,
                         scenario=sc.name)
        rows.append(r)

    _print_all(rows)
    _write_csv(rows, days)
    return rows


def _print_all(rows):
    traded = [r for r in rows if r.n_trades > 0 and not r.error]
    profitable = sum(1 for r in traded if r.total_return_pct > 0)
    beat = sum(1 for r in traded if r.excess_vs_buy_hold > 0)
    print(f"=== ALL {len(rows)} scenarios (sorted by excess vs buy-and-hold) ===")
    print(f"{'#':>3}  {'scenario':<46} {'trd':>4} {'win%':>5} {'ret%':>7} "
          f"{'PF':>6} {'DD%':>5} {'Shp':>6} {'bh%':>7} {'excess':>7}")
    for i, r in enumerate(sorted(traded, key=lambda x: x.excess_vs_buy_hold, reverse=True), 1):
        print(f"{i:>3}  {r.scenario[:46]:<46} {r.n_trades:>4} {r.win_rate:>5.0f} "
              f"{r.total_return_pct:>7.2f} {r.profit_factor:>6.2f} {r.max_drawdown_pct:>5.1f} "
              f"{r.sharpe:>6.2f} {r.buy_hold_pct:>7.2f} {r.excess_vs_buy_hold:>7.2f}")
    no_trade = [r for r in rows if r.n_trades == 0]
    if no_trade:
        print(f"\n({len(no_trade)} scenarios took 0 trades on this window — not shown above)")
    print(f"\nSUMMARY: {len(traded)} traded | {profitable} profitable net of costs "
          f"({profitable/max(len(traded),1)*100:.0f}%) | {beat} beat buy-and-hold "
          f"({beat/max(len(traded),1)*100:.0f}%)")


def _write_csv(rows, days):
    path = REPO_DIR / "logs" / f"backtest_month_{days}d.csv"
    path.parent.mkdir(exist_ok=True)
    cols = ["scenario", "n_trades", "win_rate", "total_return_pct", "profit_factor",
            "max_drawdown_pct", "sharpe", "buy_hold_pct", "excess_vs_buy_hold",
            "exposure_pct", "error"]
    df = pd.DataFrame([{c: getattr(r, c) for c in cols} for r in rows])
    df.to_csv(path, index=False)
    print(f"\n[csv] full table ({len(df)} rows) -> {path}")


if __name__ == "__main__":
    main()
