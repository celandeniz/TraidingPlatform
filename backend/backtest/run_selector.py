"""Run symbol selection over the M7 + the selection-level OOS validation.

    .venv/bin/python -m backend.backtest.run_selector
"""
from __future__ import annotations

from ..data.alpaca_provider import AlpacaProvider
from ..settings import get_config, get_settings
from .selector import select_symbols, validate_selection


def main():
    s = get_settings(); cfg = get_config()
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    data = {}
    for sym in cfg["universe"]:
        data[sym] = provider.get_recent_bars(sym, "5m", 3000)
        print(f"[data] {sym}: {len(data[sym])} bars")

    print("\n=== Symbol selection (regime-filtered WF, 4 folds) ===")
    sel = select_symbols(data, n_folds=4)
    for v in sorted(sel.verdicts, key=lambda x: x.avg_oos_return, reverse=True):
        tag = "TRADABLE " if v.tradable else "excluded "
        print(f"  [{tag}] {v.symbol:<6} {v.reason}")
    print(f"\nTRADABLE: {sel.tradable or 'NONE'}")
    print(f"EXCLUDED: {sel.excluded}")
    print(f"portfolio avg OOS — all symbols: {sel.all_avg_oos:+.2f}%  |  "
          f"tradable only: {sel.tradable_avg_oos:+.2f}%")

    print("\n=== Selection-level OUT-OF-SAMPLE validation ===")
    print("(derive whitelist on EARLY half, test those names on the LATER half)")
    v = validate_selection(data, n_folds=3)
    print(f"  early tradable : {v['early_tradable']}")
    print(f"  early excluded : {v['early_excluded']}")
    print(f"  LATE OOS of chosen   : {v['late_oos_of_chosen']}")
    print(f"  LATE OOS of excluded : {v['late_oos_of_excluded']}")
    print(f"  selection edge       : {v['selection_edge_pp']} pp")
    print(f"  VERDICT: {v['verdict']}")
    return sel, v


if __name__ == "__main__":
    main()
