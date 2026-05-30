"""Phase 1 runner: stream 1m bars -> run strategies -> print + tape.

On each closed 1m bar we keep a rolling per-symbol window, run the enabled
signal strategies, and — only if one fires — run the enabled confirmation
strategies (which lazily pull multi-timeframe bars). Every fired signal is
printed and appended to the JSONL tape. No orders are placed in Phase 1.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .data.alpaca_provider import AlpacaProvider
from .settings import get_config, get_settings
from .store import tape
from .strategy.base import BarContext
from .strategy.regime import detect as detect_regime
from .strategy.registry import (
    build_confirmation_strategies,
    build_signal_strategies,
)

ET = ZoneInfo("America/New_York")
IST = ZoneInfo("Europe/Istanbul")
MAX_WINDOW = 240  # bars kept in memory per symbol


class Engine:
    def __init__(self, config: dict, provider: AlpacaProvider):
        self.config = config
        self.provider = provider
        self.signal_strategies = build_signal_strategies(config)
        self.confirmation_strategies = build_confirmation_strategies(config)
        self.windows: dict[str, pd.DataFrame] = {}
        self.regime_cfg = config.get("regime", {})

    # ---- warmup -----------------------------------------------------------
    def warmup(self, symbols: list[str]) -> None:
        n = self.config.get("data", {}).get("warmup_bars", 60)
        tf = self.config.get("data", {}).get("bar_timeframe", "1m")
        for sym in symbols:
            try:
                df = self.provider.get_recent_bars(sym, tf, n)
                self.windows[sym] = df
                print(f"[warmup] {sym}: {len(df)} bars")
            except Exception as exc:  # noqa: BLE001 - surface, don't crash warmup
                self.windows[sym] = pd.DataFrame(
                    columns=["open", "high", "low", "close", "volume"]
                )
                print(f"[warmup] {sym}: FAILED ({exc})")

    # ---- per-bar handling -------------------------------------------------
    async def on_bar(self, symbol: str, bar: dict) -> None:
        row = pd.DataFrame(
            [
                {
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                }
            ],
            index=[pd.Timestamp(bar["timestamp"])],
        )
        win = pd.concat([self.windows.get(symbol, row.iloc[0:0]), row])
        self.windows[symbol] = win.tail(MAX_WINDOW)
        self._evaluate(symbol, bar)

    def _evaluate(self, symbol: str, bar: dict) -> None:
        win = self.windows[symbol]
        ctx = BarContext(
            symbol=symbol,
            window=win,
            config=self.config,
            get_bars=lambda tf, lb, _s=symbol: self.provider.get_recent_bars(_s, tf, lb),
        )
        regime = detect_regime(
            win,
            ema_period=self.regime_cfg.get("ema_period", 50),
            slope_threshold=self.regime_cfg.get("slope_threshold", 0.0005),
        )

        for strat in self.signal_strategies:
            sig = strat.evaluate(ctx)
            if not sig.fired:
                continue
            confirmations = [c.confirm(sig.side, ctx) for c in self.confirmation_strategies]
            self._emit(symbol, bar, strat.name, sig, regime, confirmations)

    def _emit(self, symbol, bar, strategy_name, sig, regime, confirmations) -> None:
        event = {
            "symbol": symbol,
            "strategy": strategy_name,
            "side": sig.side,
            "strength": round(sig.strength, 4),
            "close": bar["close"],
            "regime": regime,
            **{k: v for k, v in sig.meta.items()},
        }
        for c in confirmations:
            event[f"{c.name}_passed"] = c.passed
            event[f"{c.name}_score"] = c.score
            event.update(c.meta)

        tape.append(event)
        self._print(event)

    @staticmethod
    def _print(event: dict) -> None:
        now = datetime.now()
        clock = f"{now.astimezone(ET):%H:%M:%S} ET / {now.astimezone(IST):%H:%M} IST"
        bb = ""
        if "bollinger_score" in event:
            mark = "OK" if event.get("bollinger_passed") else ".."
            bb = f" | BB {int(event['bollinger_score'])}/6 [{mark}]"
        print(
            f"[{clock}] {event['symbol']:5} {event['side'].upper():4} "
            f"@ {event['close']:.2f}  z={event.get('z')} rsi={event.get('rsi')} "
            f"regime={event['regime']}{bb}"
        )


async def main() -> None:
    settings = get_settings()
    config = get_config()
    symbols = config["universe"]

    if not settings.alpaca_api_key or not settings.alpaca_api_secret:
        raise SystemExit(
            "Missing Alpaca credentials. Copy .env.example to .env and fill in keys."
        )

    provider = AlpacaProvider(
        settings.alpaca_api_key, settings.alpaca_api_secret, feed=settings.alpaca_data_feed
    )
    engine = Engine(config, provider)

    print(f"[mode] {settings.trading_mode.upper()} (no orders in Phase 1)")
    print(f"[universe] {', '.join(symbols)}")
    engine.warmup(symbols)
    print("[stream] subscribing to 1m bars... (Ctrl-C to stop)")
    await provider.stream_bars(symbols, engine.on_bar)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[stop] runner stopped.")
