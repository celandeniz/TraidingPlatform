"""Continuous paper auto-trader — runs AutoTrader.run_cycle on an interval.

    python -m backend.scripts.auto_trade_loop [--interval SEC] [--dry-run] [--max-qty N]

PAPER ONLY: refuses to start if LIVE_TRADING is enabled. Every action is routed
through the OMS + guard pipeline + RiskManager (same as a human order) and logged
to logs/auto_trader.jsonl. dry_run proposes without trading; the default submits
to the paper account.

This is the "always-on" autonomous tool: it loops forever, one cycle per
interval, degrading gracefully if a cycle errors (it logs and continues).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone


def _arg(flag: str, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


def _momentum_seeds(cfg: dict, top_n: int = 10) -> list:
    """Top-N names by 12-1 cross-sectional momentum from the DAILY cache.

    The platform's best, data-available strategy here is daily cross-sectional
    momentum (intraday/Alpaca data is starved). We compute it directly so the
    autonomous trader has real candidates to consider. Best-effort; [] on failure.
    """
    try:
        from pathlib import Path

        from backend.data.daily_cache import DailyBarCache
        from backend.strategy.xs_momentum import MIN_BARS, momentum_12_1
        from backend.universe import load_universe

        universe = sorted(load_universe({**cfg, "universe_mode": "nasdaq100"}))
        cache = DailyBarCache(Path("backend/store/daily_cache"))
        rep = cache.ensure(universe, min_years=2)
        scores = []
        for sym in rep.included:
            df = cache.get(sym)
            if df is not None and len(df) >= MIN_BARS:
                try:
                    scores.append((sym, momentum_12_1(df["close"])))
                except Exception:  # noqa: BLE001
                    continue
        scores.sort(key=lambda x: x[1], reverse=True)
        return [{"symbol": s, "score": round(m, 4), "strategy": "xs_momentum"}
                for s, m in scores[:top_n]]
    except Exception:  # noqa: BLE001 - seeding is optional
        return []


def main() -> None:
    from backend.agent.auto_trader import AutoTrader
    from backend.mcp.server import build_toolset
    from backend.research.llm_factory import build_llm_client
    from backend.settings import get_config, get_settings

    settings = get_settings()
    cfg = get_config()

    if getattr(settings, "live_trading", False):
        print("REFUSING: LIVE_TRADING is enabled. This loop is paper-only.")
        sys.exit(1)

    interval = int(_arg("--interval", 900))
    dry_run = "--dry-run" in sys.argv
    max_qty = float(_arg("--max-qty", cfg.get("auto_trader", {}).get("max_qty", 10)))
    seed = "--no-seed" not in sys.argv          # momentum seeding on by default
    seed_n = int(_arg("--seed-n", 10))

    toolset = build_toolset()              # executor -> guards -> OMS, paper
    llm = build_llm_client(settings, cfg)
    if llm is None:
        print("WARNING: no LLM provider (start Ollama or set a key) — the trader "
              "will propose nothing until one is available.")

    acfg = dict(cfg.get("auto_trader", {}))
    acfg.update({"enabled": True, "dry_run": dry_run, "max_qty": max_qty})
    trader = AutoTrader(toolset, llm, acfg)

    mode = "DRY-RUN (proposals only)" if dry_run else "PAPER (submitting orders)"
    print(f"[auto-trade] starting — {mode}, interval={interval}s, max_qty={max_qty}, "
          f"llm={type(llm).__name__ if llm else 'none'}")

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            seeds = _momentum_seeds(cfg, top_n=seed_n) if seed else None
            out = trader.run_cycle(seed_candidates=seeds)
            acted = [a for a in out.get("actions", [])
                     if a.get("status") in ("proposed", "executed")]
            print(f"[auto-trade] {ts} cycle {cycle}: proposed={out.get('n_proposed', 0)} "
                  f"acted={len(acted)} -> "
                  + ("; ".join(f"{a['status']}:{a['action']} {a['qty']} {a['symbol']}"
                               for a in acted) or "no actions"), flush=True)
        except Exception as exc:  # noqa: BLE001 - a bad cycle must not stop the loop
            print(f"[auto-trade] {ts} cycle {cycle}: ERROR {type(exc).__name__}: {exc}",
                  flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
