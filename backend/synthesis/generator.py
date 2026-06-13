"""Best-of-N candidate generation via the platform LLM.

Each candidate is Python source for ONE class implementing the runner contract
evaluate(self, ctx) -> StrategySignal. The model is given the contract, the
indicators API, and an exemplar; it must NOT import anything (the harness injects
pd / indicators / BarContext / StrategySignal) and must avoid while loops.

generate() returns [] when no LLM is configured, so the pipeline degrades.
"""
from __future__ import annotations

from dataclasses import dataclass

_SYSTEM = """You write a SINGLE Python trading-strategy class for a backtester.

HARD RULES (violation => rejected):
- Define exactly ONE class with a method: def evaluate(self, ctx) -> StrategySignal
- NO import statements. These names are already available: pd (pandas),
  indicators, BarContext, StrategySignal.
- NO while loops, no file/network/system access, no eval/exec/getattr/dunder.

CONTEXT object `ctx`:
- ctx.window : pandas DataFrame of OHLCV bars, columns open/high/low/close/volume,
  oldest..newest, tz-aware index. Use ctx.window.
- ctx.symbol : str. ctx.config : dict. ctx.get_bars(tf, n) : recent bars.

RETURN a StrategySignal(side=..., strength=...):
- side = "buy" to go long, "sell" to go short, or None for no trade.
- strength : float 0..1 (confidence). meta is optional.

indicators API (call as indicators.X): rsi(close, period), ema(close, period),
vwap(df), bollinger(close, period, k), macd(close), atr(df, period),
keltner(df, ...), zscore(series, window). Guard against short windows
(len(ctx.window) < needed) by returning StrategySignal(side=None).

EXEMPLAR (shape only — write your own logic for the user's idea):

class RsiPullback:
    def evaluate(self, ctx):
        w = ctx.window
        if len(w) < 20:
            return StrategySignal(side=None)
        r = indicators.rsi(w["close"], 14)
        last = float(r.iloc[-1])
        if last < 30:
            return StrategySignal(side="buy", strength=min(1.0, (30 - last) / 30))
        if last > 70:
            return StrategySignal(side="sell", strength=min(1.0, (last - 70) / 30))
        return StrategySignal(side=None)
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "class_name": {"type": "string", "description": "the class name you defined"},
        "source": {"type": "string", "description": "the full Python source for the class"},
        "rationale": {"type": "string", "description": "one sentence on the idea"},
    },
    "required": ["class_name", "source"],
}


@dataclass
class Candidate:
    class_name: str
    source: str
    rationale: str = ""
    index: int = 0


def _user(brief, i: int) -> str:
    nudge = ["", " Favor a trend-following reading.", " Favor a mean-reversion reading.",
             " Use a volatility/breakout angle.", " Combine two indicators.",
             " Keep it simple, one indicator.", " Add a volume confirmation.",
             " Use a longer lookback."][i % 8]
    return (f"Strategy idea: {brief.text}\nSymbol: {brief.symbol}, timeframe "
            f"{brief.timeframe}.{nudge}\nWrite the class now.")


def generate(brief, llm, n: int) -> list[Candidate]:
    if llm is None:
        return []
    out: list[Candidate] = []
    for i in range(n):
        try:
            resp = llm.structured(
                system=_SYSTEM, user=_user(brief, i),
                tool_name="emit_strategy", tool_schema=_SCHEMA,
                max_tokens=1500, use_case="coding",
            )
        except Exception:  # noqa: BLE001 - one bad generation must not kill best-of-N
            continue
        if not isinstance(resp, dict):
            continue
        source = resp.get("source") or ""
        class_name = resp.get("class_name") or ""
        if source and class_name:
            out.append(Candidate(class_name=class_name, source=source,
                                 rationale=resp.get("rationale", ""), index=i))
    return out
