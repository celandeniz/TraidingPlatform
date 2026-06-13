"""Run the strategy tournament over a chosen universe (e.g. S&P500 + NASDAQ100),
save the run, and print the gated leaderboard.

    python -m backend.scripts.run_tournament_universe [mode] [--max N]

mode: m7 | sp500 | nasdaq100 | sp500_nasdaq100  (default sp500_nasdaq100)
--max N: cap the daily/portfolio universe to the first N symbols (data/time guard)

The tournament reuses the same risk gates as /tournament; the printed leaderboard
shows passers first, ranked by out-of-sample Sharpe.
"""
from __future__ import annotations

import sys
import time

from backend.backtest.tournament import rank_reports, run_tournament, save_run
from backend.settings import get_config


def main() -> None:
    args = [a for a in sys.argv[1:]]
    mode = next((a for a in args if not a.startswith("--")), "sp500_nasdaq100")
    max_n = None
    if "--max" in args:
        max_n = int(args[args.index("--max") + 1])

    config = dict(get_config())
    config["universe_mode"] = mode
    if max_n is not None:
        from backend.universe import load_universe
        universe = sorted(load_universe(config))[:max_n]
        tcfg = dict(config.get("tournament", {}))
        tcfg["daily_symbols"] = universe
        tcfg["intraday_symbols"] = universe[:20]
        config["tournament"] = tcfg
        print(f"[tournament] universe={mode} capped to {len(universe)} symbols")
    else:
        print(f"[tournament] universe={mode} (full)")

    t0 = time.time()

    def progress(name: str, i: int, total: int) -> None:
        print(f"[{i}/{total}] {name} ... ({round(time.time() - t0)}s elapsed)", flush=True)

    run = run_tournament(config, progress=progress)
    path = save_run(run)
    print(f"\n[tournament] saved -> {path}  ({round(time.time() - t0)}s total)\n")

    print("=== LEADERBOARD (passers first, by OOS Sharpe) ===")
    for r in rank_reports(run.reports):
        gates = r.gates or {}
        status = "PASS" if gates.get("passed") else ("ERROR" if r.error else "fail")
        oos = r.metrics.get("oos_sharpe", float("nan")) if not r.error else float("nan")
        line = f"  {status:5} {r.name:24} oos_sharpe={oos:.3f}"
        if r.error:
            line += f"  error={r.error[:60]}"
        elif not gates.get("passed"):
            line += "  (" + "; ".join(gates.get("failures", []))[:80] + ")"
        print(line)


if __name__ == "__main__":
    main()
