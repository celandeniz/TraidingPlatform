"""FastAPI dashboard: WebSocket hub + REST + static single-page UI.

Endpoints
  GET  /                  -> the dashboard page
  WS   /ws                -> live stream of {type: signal|price|order|positions}
  POST /api/order         -> submit a paper order ({symbol, side, qty})
  GET  /api/positions     -> current paper positions + account
  POST /api/replay        -> replay recent bars through the engine (live-like demo)

Phase 1: paper only, spot equity. The engine reuses the same strategy pipeline
as the CLI runner; signals are broadcast to all connected browsers.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..brokers import build_routing_executor
from ..data.alpaca_provider import AlpacaProvider
from ..execution.base import OrderRequest
from ..portfolio.risk import RiskConfig, RiskManager
from ..research.copilot_agent import CopilotAgent
from ..research.llm_factory import build_llm_client
from ..research.news_provider import AlpacaNewsProvider
from ..runner import Engine
from ..settings import get_config, get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="M7 Spike-Fade Dashboard")

_settings = get_settings()
_config = get_config()
_provider = AlpacaProvider(
    _settings.alpaca_api_key, _settings.alpaca_api_secret, feed=_settings.alpaca_data_feed
)

# Routing executor: equity (Alpaca paper) + crypto (ccxt sandbox) per config.
# Wrapped in a RiskManager when risk.enabled so the kill-switch governs orders.
_routing = build_routing_executor(_settings, _config)
_risk_cfg_raw = _config.get("risk", {})
if _risk_cfg_raw.get("enabled", False):
    _executor = RiskManager(
        _routing,
        RiskConfig(
            enabled=True,
            risk_per_trade_pct=_risk_cfg_raw.get("risk_per_trade_pct", 0.5),
            max_concurrent_positions=_risk_cfg_raw.get("max_concurrent_positions", 5),
            max_position_pct=_risk_cfg_raw.get("max_position_pct", 20.0),
            max_daily_loss_pct=_risk_cfg_raw.get("max_daily_loss_pct", 3.0),
        ),
    )
else:
    _executor = _routing

# Phase 2/3 research layer. The LLM client is provider-agnostic: local Ollama by
# default (no key needed), or Claude if configured. Built lazily; None when no
# provider is usable (then copilot/committee degrade gracefully).
_copilot: CopilotAgent | None = None
_llm = None  # OllamaClient | ClaudeClient | None
_news: AlpacaNewsProvider | None = None
_rcfg = _config.get("research", {})
if _rcfg.get("enabled", True):
    _llm = build_llm_client(_settings, _config)
    if _llm is not None:
        _news = AlpacaNewsProvider(_settings.alpaca_api_key, _settings.alpaca_api_secret)
        if _rcfg.get("copilot", {}).get("enabled", False):
            _copilot = CopilotAgent(
                _llm, _news, cache_minutes=_rcfg.get("copilot", {}).get("cache_minutes", 10)
            )


class Hub:
    """Tracks connected browsers and broadcasts JSON events to all of them."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


hub = Hub()


class DashboardEngine(Engine):
    """Engine that broadcasts every fired signal to the hub instead of printing."""

    def __init__(self, config, provider, loop):
        super().__init__(config, provider)
        self._loop = loop

    def _emit(self, symbol, bar, strategy_name, sig, regime, confirmations):
        event = {
            "type": "signal",
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
        # broadcast from a sync context running in the event loop
        asyncio.run_coroutine_threadsafe(hub.broadcast(event), self._loop)


class OrderBody(BaseModel):
    symbol: str
    side: str
    qty: float = 1


class ReplayBody(BaseModel):
    bars: int = 200
    speed_ms: int = 120  # delay between bars, to animate the UI


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/positions")
async def positions() -> dict:
    return {"account": _executor.account_summary(), "positions": _executor.list_positions()}


@app.post("/api/order")
async def order(body: OrderBody) -> dict:
    result = _executor.submit(OrderRequest(symbol=body.symbol, side=body.side, qty=body.qty))
    event = {
        "type": "order",
        "ok": result.ok,
        "symbol": result.symbol,
        "side": result.side,
        "qty": result.qty,
        "status": result.status,
        "detail": result.detail,
    }
    await hub.broadcast(event)
    return event


@app.post("/api/replay")
async def replay(body: ReplayBody) -> dict:
    """Feed recent 1m bars through the engine to animate the dashboard live-like."""
    loop = asyncio.get_running_loop()
    engine = DashboardEngine(_config, _provider, loop)
    symbols = _config["universe"]

    async def run() -> None:
        # Pull all symbols' bars first (REST), then interleave by time.
        frames = {}
        for sym in symbols:
            df = _provider.get_recent_bars(sym, "1m", body.bars)
            if not df.empty:
                frames[sym] = df
                engine.windows[sym] = df.iloc[0:0]
        max_len = max((len(df) for df in frames.values()), default=0)
        for i in range(max_len):
            for sym, df in frames.items():
                if i >= len(df):
                    continue
                ts = df.index[i]
                row = df.iloc[i]
                bar = {
                    "timestamp": ts,
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
                engine.windows[sym] = pd.concat(
                    [engine.windows[sym], pd.DataFrame([row], index=[ts])]
                )
                await hub.broadcast(
                    {"type": "price", "symbol": sym, "close": float(row["close"]), "ts": str(ts)}
                )
                engine._evaluate(sym, bar)
            await asyncio.sleep(body.speed_ms / 1000.0)
        await hub.broadcast({"type": "replay_done"})

    asyncio.create_task(run())
    return {"started": True, "symbols": symbols, "bars": body.bars}


@app.get("/api/copilot/{symbol}")
async def copilot(symbol: str) -> dict:
    """On-demand 'why is it moving?' research for one symbol (Claude)."""
    if _copilot is None:
        return {
            "type": "catalyst_update", "symbol": symbol, "available": False,
            "summary": "Co-pilot disabled (set ANTHROPIC_API_KEY and research.copilot.enabled).",
            "tag": "none", "headlines": [],
        }
    import asyncio as _a

    ctx = await _a.to_thread(_copilot.explain, symbol.upper())
    event = {
        "type": "catalyst_update", "symbol": ctx.symbol, "available": True,
        "summary": ctx.summary, "tag": ctx.tag, "headlines": ctx.headlines,
    }
    await hub.broadcast(event)
    return event


@app.get("/api/committee/{symbol}")
async def committee(symbol: str) -> dict:
    """On-demand TradingAgents-style committee verdict for one symbol (Claude)."""
    ccfg = _rcfg.get("committee", {})
    if _llm is None or not ccfg.get("enabled", False):
        return {"type": "committee_update", "symbol": symbol, "available": False,
                "summary": "Committee disabled (enable research.committee.enabled; "
                           "needs Ollama running or an Anthropic key).", "side": "pass"}
    import asyncio as _a

    from ..research.agents.committee import run_committee
    from ..research.catalyst_gate import evaluate as gate_eval

    sym = symbol.upper()

    def _run():
        headlines = [h.headline for h in _news.recent_headlines(sym, limit=3)] if _news else []
        gate = gate_eval("buy", regime="range", news_ages_minutes=[],
                         earnings_in_days=None, gap_pct=None)
        return run_committee(_llm, sym, "buy", context=f"On-demand review of {sym}.",
                             headlines=headlines, gate=gate, bb_meta={}, cfg=ccfg)

    v = await _a.to_thread(_run)
    event = {
        "type": "committee_update", "symbol": v.symbol, "available": v.available,
        "side": v.side, "confidence": v.confidence, "rationale": v.rationale,
        "rounds": v.rounds_run, "cost_usd": round(v.cost_usd, 4),
        "analysts": [{"role": a.role, "side": a.side, "confidence": a.confidence}
                     for a in v.analyst_reports],
        "debate": [{"side": t.side, "round": t.round, "argument": t.argument}
                   for t in v.debate],
    }
    await hub.broadcast(event)
    return event


class BacktestBody(BaseModel):
    symbol: str = "MSFT"
    timeframe: str = "5m"
    strategy: str = "spike_fade"   # spike_fade | ema_momentum | donchian
    take_profit_pct: float = 2.0
    stop_loss_pct: float = 1.5
    bars: int = 2000


@app.post("/api/backtest")
async def backtest(body: BacktestBody) -> dict:
    """Run ONE realistic backtest (no lookahead, costs in) on real bars; AI-analyzed."""
    import asyncio as _a

    from ..backtest.analyze import analyze_results
    from ..backtest.engine import CostModel, ExitParams, run_backtest
    from ..strategy.donchian_breakout import generate as donch
    from ..strategy.ema_momentum import generate as ema
    from ..strategy.spike_fade import generate as spike

    fns = {
        "spike_fade": lambda df: spike(df, zscore_window=20, lookback_k=2, z_entry=2.0),
        "ema_momentum": lambda df: ema(df, fast=12, slow=26),
        "donchian": lambda df: donch(df, channel=20),
    }
    fn = fns.get(body.strategy, fns["spike_fade"])

    def _run():
        df = _provider.get_recent_bars(body.symbol.upper(), body.timeframe, body.bars)
        res = run_backtest(
            df, fn,
            exits=ExitParams(body.take_profit_pct, body.stop_loss_pct, 0.8, 90, True),
            costs=CostModel(1.0, 2.0), warmup=35,
            scenario=f"{body.symbol}|{body.timeframe}|{body.strategy}",
        )
        analysis = analyze_results([res], _llm)
        return df, res, analysis

    try:
        df, res, analysis = await _a.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}

    # Candles + trade markers for the UI chart. Timestamps are epoch seconds
    # (lightweight-charts format). entry/exit indices map to the df index.
    def _epoch(ts):
        return int(ts.timestamp())

    candles = [
        {"time": _epoch(ts), "open": float(r.open), "high": float(r.high),
         "low": float(r.low), "close": float(r.close)}
        for ts, r in df.iterrows()
    ]
    idx = df.index
    markers = []
    for t in res.trades:
        markers.append({"time": _epoch(idx[t.entry_idx]), "kind": "entry",
                        "side": t.side, "price": round(t.entry_px, 2)})
        markers.append({"time": _epoch(idx[t.exit_idx]), "kind": "exit",
                        "side": t.side, "price": round(t.exit_px, 2),
                        "reason": t.reason, "ret_pct": round(t.ret_pct, 2)})
    trades = [
        {"side": t.side, "entry_time": _epoch(idx[t.entry_idx]),
         "exit_time": _epoch(idx[t.exit_idx]), "entry_px": round(t.entry_px, 2),
         "exit_px": round(t.exit_px, 2), "bars_held": t.bars_held,
         "reason": t.reason, "ret_pct": round(t.ret_pct, 2)}
        for t in res.trades
    ]
    return {
        "ok": True, "scenario": res.scenario, "symbol": body.symbol.upper(),
        "n_trades": res.n_trades,
        "win_rate": round(res.win_rate, 1), "total_return_pct": round(res.total_return_pct, 2),
        "profit_factor": res.profit_factor, "max_drawdown_pct": round(res.max_drawdown_pct, 1),
        "sharpe": res.sharpe, "buy_hold_pct": round(res.buy_hold_pct, 2),
        "excess_vs_buy_hold": round(res.excess_vs_buy_hold, 2),
        "exposure_pct": round(res.exposure_pct, 1), "error": res.error,
        "candles": candles, "markers": markers, "trades": trades,
        "ai": {"verdict": analysis.get("verdict"), "caveats": analysis.get("caveats"),
               "available": analysis.get("available")},
    }


@app.get("/api/backtest/scenarios")
async def backtest_scenarios() -> dict:
    """Return the saved 250-scenario month grid (logs/backtest_month_30d.csv)."""
    import csv as _csv

    from ..settings import REPO_DIR

    path = REPO_DIR / "logs" / "backtest_month_30d.csv"
    if not path.exists():
        return {"ok": False, "detail": "Run `python -m backend.backtest.run_month` first.",
                "rows": []}
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            try:
                rows.append({
                    "scenario": r["scenario"], "n_trades": int(float(r["n_trades"])),
                    "win_rate": round(float(r["win_rate"]), 1),
                    "total_return_pct": round(float(r["total_return_pct"]), 2),
                    "profit_factor": round(float(r["profit_factor"]), 2),
                    "max_drawdown_pct": round(float(r["max_drawdown_pct"]), 1),
                    "sharpe": round(float(r["sharpe"]), 2),
                    "buy_hold_pct": round(float(r["buy_hold_pct"]), 2),
                    "excess_vs_buy_hold": round(float(r["excess_vs_buy_hold"]), 2),
                })
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda x: x["excess_vs_buy_hold"], reverse=True)
    return {"ok": True, "count": len(rows), "rows": rows}


@app.get("/api/agent/roles")
async def agent_roles() -> dict:
    """List business-agent roles and the local model each auto-resolves to."""
    if _llm is None or not hasattr(_llm, "available_roles"):
        return {"available": False, "roles": {}}
    return {"available": True, "roles": _llm.available_roles()}


class AgentRunBody(BaseModel):
    prompt: str
    role: Optional[str] = None      # auto-select model by role
    model: Optional[str] = None     # OR manual override (exact model name)
    system: str = "You are a helpful assistant. Answer concisely."


@app.post("/api/agent/run")
async def agent_run(body: AgentRunBody) -> dict:
    """Run a free-form agent request; model chosen by role (auto) or model (manual)."""
    if _llm is None:
        return {"available": False, "detail": "No LLM provider (start Ollama or set a key)."}
    import asyncio as _a

    schema = {"type": "object",
              "properties": {"answer": {"type": "string"}},
              "required": ["answer"]}

    def _run():
        return _llm.structured(
            system=body.system, user=body.prompt, tool_name="answer",
            tool_schema=schema, max_tokens=800, role=body.role, model=body.model,
        )

    resolved = None
    if hasattr(_llm, "resolve_model"):
        resolved = _llm.resolve_model(role=body.role, model=body.model)
    try:
        out = await _a.to_thread(_run)
        return {"available": True, "model": resolved, "role": body.role,
                "answer": out.get("answer", "")}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "model": resolved, "detail": str(exc)}


@app.post("/api/kill_switch")
async def kill_switch() -> dict:
    """Manually engage the risk kill-switch — blocks new opens (closes still allowed)."""
    if isinstance(_executor, RiskManager):
        _executor.engage_kill_switch("manual (dashboard)")
        await hub.broadcast({"type": "kill", "engaged": True, "reason": "manual"})
        return {"engaged": True}
    return {"engaged": False, "detail": "risk manager not active (risk.enabled=false)"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        await ws.send_text(json.dumps({"type": "hello", "universe": _config["universe"]}))
        while True:
            await ws.receive_text()  # keepalive; client doesn't need to send
    except WebSocketDisconnect:
        hub.disconnect(ws)
