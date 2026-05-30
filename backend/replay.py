"""Offline pipeline demo: replay recent 1m bars through the engine.

Lets us exercise the full signal -> confirmation -> tape path on real Alpaca data
without waiting for a live session. Run:

    .venv/bin/python -m backend.replay [N_BARS]

CAVEAT: this is a pipeline smoke-test, not a backtest. Bollinger confirmation
calls get_recent_bars for *current* multi-TF bars (not point-in-time), so the
confirmation column is indicative only here. Live mode has no such issue.
"""
from __future__ import annotations

import sys

import pandas as pd

from .data.alpaca_provider import AlpacaProvider
from .runner import Engine
from .settings import get_config, get_settings


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    s = get_settings()
    cfg = get_config()
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    engine = Engine(cfg, provider)

    fired = 0
    for sym in cfg["universe"]:
        df = provider.get_recent_bars(sym, "1m", n)
        if df.empty:
            print(f"[replay] {sym}: no bars")
            continue
        # Seed window empty, then feed bars one by one (closed-bar semantics).
        engine.windows[sym] = df.iloc[0:0]
        before = _tape_count()
        for ts, row in df.iterrows():
            bar = {
                "timestamp": ts,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            # synchronous path (engine._evaluate) — no asyncio needed for replay
            win = pd.concat([engine.windows[sym], pd.DataFrame([row], index=[ts])])
            engine.windows[sym] = win
            engine._evaluate(sym, bar)
        after = _tape_count()
        n_sym = after - before
        fired += n_sym
        print(f"[replay] {sym}: {len(df)} bars -> {n_sym} signals")

    print(f"\n[replay] total signals fired & taped: {fired}")
    print("[replay] tape file: see logs/tape_*.jsonl")


def _tape_count() -> int:
    from datetime import datetime, timezone

    from .store.tape import _path_for

    p = _path_for(datetime.now(timezone.utc))
    if not p.exists():
        return 0
    return sum(1 for _ in open(p, encoding="utf-8"))


if __name__ == "__main__":
    main()
