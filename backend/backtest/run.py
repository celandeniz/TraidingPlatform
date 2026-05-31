"""Run the scenario grid on REAL Alpaca data and report — honestly.

Usage:
    .venv/bin/python -m backend.backtest.run [n_scenarios]

No lookahead (see engine.py). Data is fetched once per (symbol, timeframe) and
reused. After the grid runs, an optional AI pass (local Ollama) summarizes the
results and ranks the most robust configs — see analyze.py.
"""
from __future__ import annotations

import sys

from ..data.alpaca_provider import AlpacaProvider
from ..settings import get_config, get_settings
from .engine import CostModel, run_backtest
from .scenarios import build_scenarios

# Bars to request per timeframe (bounded by the free Alpaca feed history).
TF_LOOKBACK = {"1m": 2000, "5m": 2000, "15m": 2000, "1h": 2000}


def fetch_data(provider, symbols, timeframes):
    cache = {}
    for sym in symbols:
        for tf in timeframes:
            try:
                df = provider.get_recent_bars(sym, tf, TF_LOOKBACK.get(tf, 1500))
                cache[(sym, tf)] = df
                print(f"[data] {sym} {tf}: {len(df)} bars")
            except Exception as exc:  # noqa: BLE001
                cache[(sym, tf)] = None
                print(f"[data] {sym} {tf}: FAILED ({exc})")
    return cache


def run_grid(n_scenarios=250):
    settings = get_settings()
    cfg = get_config()
    provider = AlpacaProvider(settings.alpaca_api_key, settings.alpaca_api_secret,
                              feed=settings.alpaca_data_feed)
    symbols = cfg["universe"][:5]            # keep the grid tractable
    timeframes = ["5m", "15m", "1h"]         # intraday frames with usable history
    costs = CostModel(commission_bps=1.0, slippage_bps=2.0)

    data = fetch_data(provider, symbols, timeframes)
    scenarios = build_scenarios(symbols, timeframes, target=n_scenarios)
    print(f"\n[grid] running {len(scenarios)} scenarios (no lookahead, "
          f"next-bar-open fills, {costs.commission_bps + costs.slippage_bps:.0f}bps round-cost)\n")

    results = []
    for sc in scenarios:
        df = data.get((sc.symbol, sc.timeframe))
        if df is None or len(df) < 60:
            continue
        res = run_backtest(df, sc.signal_fn, exits=sc.exits, costs=costs,
                           warmup=35, scenario=sc.name)
        results.append(res)
    return results


def report(results):
    traded = [r for r in results if r.n_trades > 0 and not r.error]
    print(f"=== {len(results)} scenarios run, {len(traded)} took trades ===\n")
    if not traded:
        print("No scenarios produced trades on the available data.")
        return traded

    profitable = [r for r in traded if r.total_return_pct > 0]
    beat_bh = [r for r in traded if r.excess_vs_buy_hold > 0]
    print(f"profitable (net of costs): {len(profitable)}/{len(traded)} "
          f"({len(profitable)/len(traded)*100:.0f}%)")
    print(f"beat buy-and-hold:         {len(beat_bh)}/{len(traded)} "
          f"({len(beat_bh)/len(traded)*100:.0f}%)\n")

    # Rank by excess-vs-buy-hold then profit factor (robustness, not raw return).
    top = sorted(traded, key=lambda r: (r.excess_vs_buy_hold, r.profit_factor), reverse=True)[:10]
    print("TOP 10 by excess-vs-buy-hold:")
    print(f"  {'scenario':<46} {'trades':>6} {'win%':>6} {'ret%':>7} {'PF':>6} "
          f"{'DD%':>6} {'Shp':>6} {'bh%':>7} {'excess':>7}")
    for r in top:
        print(f"  {r.scenario[:46]:<46} {r.n_trades:>6} {r.win_rate:>6.0f} "
              f"{r.total_return_pct:>7.2f} {r.profit_factor:>6.2f} "
              f"{r.max_drawdown_pct:>6.1f} {r.sharpe:>6.2f} {r.buy_hold_pct:>7.2f} "
              f"{r.excess_vs_buy_hold:>7.2f}")

    worst = sorted(traded, key=lambda r: r.total_return_pct)[:5]
    print("\nWORST 5 (honest — these LOSE money):")
    for r in worst:
        print(f"  {r.scenario[:46]:<46} ret={r.total_return_pct:>7.2f}% "
              f"trades={r.n_trades} PF={r.profit_factor:.2f}")
    return traded


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    results = run_grid(n)
    traded = report(results)

    # AI pass: local model (analysis role -> deepseek-r1) interprets the grid.
    from ..research.llm_factory import build_llm_client
    from .analyze import analyze_results

    llm = build_llm_client(get_settings(), get_config())
    print(f"\n=== AI analysis ({'local: ' + type(llm).__name__ if llm else 'rule-based'}) ===")
    a = analyze_results(results, llm)
    print("verdict      :", a.get("verdict"))
    print("top picks    :", a.get("top_picks"))
    print("overfit risk :", a.get("overfitting_risk"))
    print("caveats      :", a.get("caveats"))
    return results, traded, a


if __name__ == "__main__":
    main()
