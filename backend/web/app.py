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

from ..data.alpaca_provider import AlpacaProvider
from ..execution.base import OrderRequest
from ..execution.paper import PaperExecutionAdapter
from ..runner import Engine
from ..settings import get_config, get_settings

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="M7 Spike-Fade Dashboard")

_settings = get_settings()
_config = get_config()
_provider = AlpacaProvider(
    _settings.alpaca_api_key, _settings.alpaca_api_secret, feed=_settings.alpaca_data_feed
)
_executor = PaperExecutionAdapter(_settings.alpaca_api_key, _settings.alpaca_api_secret)


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


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        await ws.send_text(json.dumps({"type": "hello", "universe": _config["universe"]}))
        while True:
            await ws.receive_text()  # keepalive; client doesn't need to send
    except WebSocketDisconnect:
        hub.disconnect(ws)
