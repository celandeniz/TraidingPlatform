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

# Strategy -> regime alignment (the (A) improvement, validated in walk-forward).
# Mean-reversion only in range; momentum/breakout only with the trend.
_MEAN_REVERSION = {"spike_fade", "rsi_reversion", "vwap_reversion"}
_TREND_FOLLOWING = {"ema_momentum", "donchian_breakout", "macd_cross",
                    "keltner_breakout", "atr_trend"}


def regime_allows(strategy_name: str, side, regime: str) -> bool:
    """True if this strategy's signal is aligned with the current regime.

    spike_fade  -> only in 'range' (don't fade a trend).
    ema/donchian-> only with the trend (long in up, short in down); not in range.
    Unknown strategies are always allowed (no opinion).
    """
    if strategy_name in _MEAN_REVERSION:
        return regime == "range"
    if strategy_name in _TREND_FOLLOWING:
        if regime == "up":
            return side == "buy"
        if regime == "down":
            return side == "sell"
        return False  # range: no trend to follow
    return True


class Engine:
    def __init__(self, config: dict, provider: AlpacaProvider, executor=None,
                 position_manager=None):
        self.config = config
        self.provider = provider
        self.signal_strategies = build_signal_strategies(config)
        self.confirmation_strategies = build_confirmation_strategies(config)
        self.windows: dict[str, pd.DataFrame] = {}
        self.regime_cfg = config.get("regime", {})
        # (A) regime filter: align strategies with the regime. On by default
        # (walk-forward showed it improves out-of-sample); toggle via config.
        self.regime_filter = self.regime_cfg.get("filter_enabled", True)
        # Execution is opt-in: active only when risk.enabled AND a manager is given.
        # Default (Phase 1/2) = None => detect+log signals only, no orders.
        self.executor = executor
        self.position_manager = position_manager
        self.risk_enabled = bool(config.get("risk", {}).get("enabled", False)) and \
            position_manager is not None

    # ---- hot promotion ----------------------------------------------------
    def reload_generated_strategies(self) -> int:
        """Merge promoted (LLM-generated) strategies into the live signal set
        without a restart. Replaces any previously merged generated ones and
        returns how many are now loaded. Generated strategies are paper-only."""
        from .strategy.registry import build_generated_signal_strategies

        self.signal_strategies = [s for s in self.signal_strategies
                                  if not getattr(s, "_generated", False)]
        generated = build_generated_signal_strategies()
        self.signal_strategies.extend(generated)
        return len(generated)

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
        # Manage any open position on this symbol first (exit rules), then evaluate.
        if self.risk_enabled:
            self.position_manager.manage(symbol, float(bar["close"]))
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
            # (A) regime filter: skip signals misaligned with the regime, when enabled.
            if self.regime_filter and not regime_allows(strat.name, sig.side, regime):
                continue
            confirmations = [c.confirm(sig.side, ctx) for c in self.confirmation_strategies]
            self._emit(symbol, bar, strat.name, sig, regime, confirmations)
            if self.risk_enabled:
                self._maybe_open(symbol, bar, sig, regime)

    def _maybe_open(self, symbol, bar, sig, regime) -> None:
        """Risk-gated automated open: catalyst gate -> decide(core/spot) -> size -> open.

        Tier is forced to 'core' so automation only ever takes SPOT long/short
        (options stay manual). Short requires risk.allow_equity_short. All orders
        pass through the RiskManager (kill-switch, caps, market hours) and the
        PositionManager (at most one position per symbol).
        """
        from .portfolio.risk import position_size
        from .research.catalyst_gate import evaluate as gate_eval
        from .research.decision_layer import decide

        rcfg = self.config.get("risk", {})
        gate = gate_eval(sig.side, regime=regime, news_ages_minutes=[],
                         earnings_in_days=None, gap_pct=None)
        decision = decide(symbol, sig.side, tier="core", regime=regime, gate=gate,
                          allow_spot_short=rcfg.get("allow_equity_short", False))
        if decision.action not in ("SPOT_LONG", "SPOT_SHORT"):
            return
        mark = float(bar["close"])
        acct = self.executor.account_summary() if self.executor else {}
        equity = float(acct.get("equity", 0) or 0)
        stop_pct = self.config.get("exits", {}).get("stop_loss_pct", 1.0)
        stop = mark * (1 - stop_pct / 100.0) if sig.side == "buy" else mark * (1 + stop_pct / 100.0)
        qty = position_size(equity, mark, stop, rcfg.get("risk_per_trade_pct", 0.5),
                            rcfg.get("max_position_pct", 20.0))
        if qty <= 0:
            return
        self.position_manager.open_from_decision(decision, mark, qty)

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
