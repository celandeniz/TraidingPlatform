"""Quick Alpaca paper connectivity check (no streaming, no orders).

Verifies credentials by reading the paper account, then pulls a few recent bars
for one symbol across the configured timeframes. Run:

    .venv/bin/python -m backend.smoke_test
"""
from __future__ import annotations

from alpaca.trading.client import TradingClient

from .data.alpaca_provider import AlpacaProvider
from .settings import get_config, get_settings


def main() -> None:
    s = get_settings()
    cfg = get_config()
    if not s.alpaca_api_key or not s.alpaca_api_secret:
        raise SystemExit("No Alpaca keys. Copy .env.example to .env and fill them in.")

    print("== Account ==")
    tc = TradingClient(s.alpaca_api_key, s.alpaca_api_secret, paper=True)
    acct = tc.get_account()
    print(f"  status     : {acct.status}")
    print(f"  account #  : {acct.account_number}")
    print(f"  cash       : ${acct.cash}")
    print(f"  buying pwr : ${acct.buying_power}")

    print("\n== Recent bars (data feed: %s) ==" % s.alpaca_data_feed)
    provider = AlpacaProvider(s.alpaca_api_key, s.alpaca_api_secret, feed=s.alpaca_data_feed)
    sym = cfg["universe"][0]
    for tf in cfg["bollinger"]["timeframes"]:
        try:
            df = provider.get_recent_bars(sym, tf, 5)
            last = df["close"].iloc[-1] if len(df) else "n/a"
            print(f"  {sym} {tf:>4}: {len(df)} bars, last close = {last}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {sym} {tf:>4}: ERROR {exc}")

    print("\nOK — connection works.")


if __name__ == "__main__":
    main()
