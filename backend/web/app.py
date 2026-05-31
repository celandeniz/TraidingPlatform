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
