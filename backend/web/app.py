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
import importlib.util
import json
import os
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
from ..settings import BACKEND_DIR, REPO_DIR, get_config, get_raw_config, get_settings
from ..profiles import feature_toggles, profile_summaries, set_active_profile

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


# Phase C automation surfaces (OpenAlice merge). All opt-in via config; the
# objects are built only when their flag is on so the default app is unchanged.
_snapshots = None  # SnapshotStore | None
if _config.get("snapshots", {}).get("enabled", False):
    from ..portfolio.snapshots import SnapshotStore

    _snapshots = SnapshotStore()

_event_log = None  # EventLog | None
if _config.get("scheduler", {}).get("enabled", False):
    from ..scheduler.core import EventLog

    _event_log = EventLog()

_rss = None  # RssNewsAggregator | None
_rss_cfg = _config.get("news_rss", {})
if _rss_cfg.get("enabled", False) and _rss_cfg.get("feeds"):
    from ..research.news_rss import RssNewsAggregator

    _rss = RssNewsAggregator(_rss_cfg["feeds"],
                             retention_days=_rss_cfg.get("retention_days", 14))

# Unified news across every available source: Alpaca (if keys) + RSS (if enabled) +
# Yahoo Finance (free, lazy). Built best-effort so /api/news/* works out of the box.
from ..marketdata.yahoo_provider import YahooProvider  # noqa: E402
from ..research.news_aggregator import UnifiedNews  # noqa: E402

_news_unified = UnifiedNews(alpaca=_news, rss=_rss, yahoo=YahooProvider())

# Phase D: order ledger (Trading-as-Git) over the same executor, and a simple
# in-memory Inbox push channel (workspace -> user).
from ..execution.analytics import ExecutionAnalytics  # noqa: E402
from ..oms.ledger import OrderManager  # noqa: E402

# Transaction-cost analytics records slippage vs arrival for every pushed order.
_exec_analytics = ExecutionAnalytics()
_oms = OrderManager(_executor, analytics=_exec_analytics)
_inbox: list[dict] = []

# Perspective (FINOS) streaming tables — built only when enabled and the optional
# perspective package is installed; otherwise the feed is disabled and skipped.
_perspective = None
if _config.get("perspective", {}).get("enabled", False):
    from .perspective_server import PerspectiveFeed

    _pf = PerspectiveFeed()
    _perspective = _pf if _pf.available else None


class Hub:
    """Tracks connected browsers and broadcasts JSON events to all of them."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.sinks: list = []  # extra consumers (e.g. Perspective) fed every event

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, event: dict) -> None:
        for sink in self.sinks:
            try:
                sink(event)
            except Exception:  # noqa: BLE001 - a sink must never break the broadcast
                pass
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(json.dumps(event, default=str))
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


hub = Hub()
if _perspective is not None:
    hub.sinks.append(_perspective.feed)  # forward every broadcast into Perspective


# --- WebSocket origin allow-list (anti Cross-Site WebSocket Hijacking) --------
# A browser sends an Origin header on WS handshakes; a malicious page on another
# origin could otherwise open our socket and read the live trade stream. We allow
# same-origin/localhost by default, plus anything in web.allowed_ws_origins.
# Non-browser clients (CLI, tests) send no Origin and are allowed through.
_ALLOWED_WS_ORIGINS = set(_config.get("web", {}).get("allowed_ws_origins", []) or [])


def _ws_origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser client (no Origin header)
    if origin in _ALLOWED_WS_ORIGINS:
        return True
    try:
        from urllib.parse import urlparse

        host = (urlparse(origin).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return host in ("localhost", "127.0.0.1", "::1")


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


class ProfileActivateBody(BaseModel):
    name: str


class ReplayBody(BaseModel):
    bars: int = 200
    speed_ms: int = 120  # delay between bars, to animate the UI


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/setup")
async def setup() -> FileResponse:
    return FileResponse(STATIC_DIR / "setup.html")


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


def _rebuild_runtime_for_config(config: dict) -> None:
    """Rebuild config-dependent module globals after an in-process profile switch."""
    global _config, _routing, _executor, _rcfg, _exec_analytics, _oms, _ALLOWED_WS_ORIGINS
    _config = config
    _routing = build_routing_executor(_settings, _config)
    risk_cfg_raw = _config.get("risk", {})
    if risk_cfg_raw.get("enabled", False):
        _executor = RiskManager(
            _routing,
            RiskConfig(
                enabled=True,
                risk_per_trade_pct=risk_cfg_raw.get("risk_per_trade_pct", 0.5),
                max_concurrent_positions=risk_cfg_raw.get("max_concurrent_positions", 5),
                max_position_pct=risk_cfg_raw.get("max_position_pct", 20.0),
                max_daily_loss_pct=risk_cfg_raw.get("max_daily_loss_pct", 3.0),
            ),
        )
    else:
        _executor = _routing
    _rcfg = _config.get("research", {})
    _exec_analytics = ExecutionAnalytics()
    _oms = OrderManager(_executor, analytics=_exec_analytics)
    _ALLOWED_WS_ORIGINS = set(_config.get("web", {}).get("allowed_ws_origins", []) or [])


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _env_file_value(env_name: str) -> str:
    for path in (REPO_DIR / ".env", BACKEND_DIR / ".env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == env_name:
                return value.split("#", 1)[0].strip().strip('"').strip("'")
    return ""


def _env_or_setting(env_name: str, attr: str | None = None) -> bool:
    if os.environ.get(env_name):
        return True
    return bool(_env_file_value(env_name))


def _llm_provider_status() -> dict:
    statuses = {
        "anthropic": _importable("anthropic") and _env_or_setting("ANTHROPIC_API_KEY"),
        # Gemini uses the google-genai SDK (module `google.genai`).
        "gemini": _importable("google.genai")
        and (_env_or_setting("GOOGLE_API_KEY") or _env_or_setting("GEMINI_API_KEY")),
        # DeepSeek/OpenAI-compat clients call the HTTP API via requests (no openai pkg).
        "deepseek": _importable("requests") and _env_or_setting("DEEPSEEK_API_KEY"),
        "openai": _importable("requests") and _env_or_setting("OPENAI_API_KEY"),
    }
    try:
        import urllib.request

        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=0.25) as resp:
            statuses["ollama"] = 200 <= resp.status < 500
    except Exception:  # noqa: BLE001 - local model server is optional
        statuses["ollama"] = False
    return statuses


@app.get("/api/profiles")
async def profiles_api() -> dict:
    return {
        "profiles": profile_summaries(get_raw_config()),
        "active": _config.get("active_profile"),
        "active_features": feature_toggles(_config),
    }


@app.post("/api/profiles/activate")
async def profiles_activate(body: ProfileActivateBody) -> dict:
    profiles = _config.get("profiles") or {}
    if body.name not in profiles:
        raise HTTPException(status_code=400, detail=f"unknown profile: {body.name}")
    set_active_profile(body.name)
    get_config.cache_clear()
    config = get_config()
    _rebuild_runtime_for_config(config)
    return {
        "ok": True,
        "active": config.get("active_profile"),
        "active_features": feature_toggles(config),
    }


@app.get("/api/setup/status")
async def setup_status() -> dict:
    optional_deps = {
        "openbb": _importable("openbb"),
        "ib_async": _importable("ib_async"),
        "yfinance": _importable("yfinance"),
        "google-genai": _importable("google.genai"),
        "perspective": _importable("perspective"),
        "mcp": _importable("mcp"),
        "croniter": _importable("croniter"),
        "feedparser": _importable("feedparser"),
        "python_docx": _importable("docx"),
        "reportlab": _importable("reportlab"),
    }
    api_keys_set = {
        "ALPACA_API_KEY": _env_or_setting("ALPACA_API_KEY", "alpaca_api_key"),
        "ALPACA_SECRET_KEY": _env_or_setting("ALPACA_SECRET_KEY", "alpaca_api_secret"),
        "ALPACA_BASE_URL": _env_or_setting("ALPACA_BASE_URL", "alpaca_paper_base_url"),
        "CCXT_API_KEY": _env_or_setting("CCXT_API_KEY", "ccxt_api_key"),
        "CCXT_SECRET_KEY": _env_or_setting("CCXT_SECRET_KEY", "ccxt_api_secret"),
        "ANTHROPIC_API_KEY": _env_or_setting("ANTHROPIC_API_KEY", "anthropic_api_key"),
        "GOOGLE_API_KEY": _env_or_setting("GOOGLE_API_KEY", "google_api_key"),
        "GEMINI_API_KEY": _env_or_setting("GEMINI_API_KEY", "gemini_api_key"),
        "DEEPSEEK_API_KEY": _env_or_setting("DEEPSEEK_API_KEY", "deepseek_api_key"),
        "OPENAI_API_KEY": _env_or_setting("OPENAI_API_KEY", "openai_api_key"),
        "OPENAI_BASE_URL": _env_or_setting("OPENAI_BASE_URL", "openai_base_url"),
        "FMP_API_KEY": _env_or_setting("FMP_API_KEY", "fmp_api_key"),
        "POLYGON_API_KEY": _env_or_setting("POLYGON_API_KEY", "polygon_api_key"),
        "LIVE_TRADING": _env_or_setting("LIVE_TRADING", "live_trading"),
        "TRADING_MODE": _env_or_setting("TRADING_MODE", "trading_mode"),
        "PROFILE": _env_or_setting("PROFILE", "profile"),
    }
    return {
        "optional_deps": optional_deps,
        "api_keys_set": api_keys_set,
        "llm_providers_reachable": _llm_provider_status(),
    }


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
        # Feed the dedicated sentiment analyst from ALL sources (Alpaca+RSS+Yahoo),
        # not just 3 Alpaca headlines.
        headlines = [h.headline for h in _news_unified.latest(symbol=sym, limit=12)]
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
    from ..strategy.atr_trend import generate as atr_g
    from ..strategy.donchian_breakout import generate as donch
    from ..strategy.ema_momentum import generate as ema
    from ..strategy.keltner_breakout import generate as kelt
    from ..strategy.macd_cross import generate as macd_g
    from ..strategy.rsi_reversion import generate as rsi_g
    from ..strategy.spike_fade import generate as spike
    from ..strategy.vwap_reversion import generate as vwap_g

    fns = {
        "spike_fade": lambda df: spike(df, zscore_window=20, lookback_k=2, z_entry=2.0),
        "ema_momentum": lambda df: ema(df, fast=12, slow=26),
        "donchian": lambda df: donch(df, channel=20),
        "rsi_reversion": lambda df: rsi_g(df, period=14),
        "macd_cross": lambda df: macd_g(df, fast=12, slow=26),
        "vwap_reversion": lambda df: vwap_g(df, band_pct=1.0),
        "keltner_breakout": lambda df: kelt(df, period=20, mult=2.0),
        "atr_trend": lambda df: atr_g(df, period=20, k=1.5),
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
        "p_value": res.p_value, "significant": res.significant,
        "ci_low_pct": res.ci_low_pct, "ci_high_pct": res.ci_high_pct,
        "significance_label": res.significance_label,
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


class WalkForwardBody(BaseModel):
    symbol: str = "MSFT"
    timeframe: str = "5m"
    folds: int = 4
    regime_filtered: bool = True   # apply the (A) regime improvement
    bars: int = 3000


@app.post("/api/walkforward")
async def walkforward_run(body: WalkForwardBody) -> dict:
    """Walk-forward (out-of-sample) on one symbol; honest IS->OOS degradation."""
    import asyncio as _a

    from ..backtest.engine import ExitParams
    from ..backtest.regime_filter import range_only, with_trend
    from ..backtest.walkforward import Candidate, walk_forward
    from ..strategy.donchian_breakout import generate as donch
    from ..strategy.ema_momentum import generate as ema
    from ..strategy.spike_fade import generate as spike

    ex = ExitParams(2.0, 1.5, 0.8, 90, True)

    def _cands():
        out = []
        if body.regime_filtered:
            for ze in (1.5, 2.0):
                for k in (2, 3):
                    base = lambda d, ze=ze, k=k: spike(d, zscore_window=20, lookback_k=k, z_entry=ze)
                    out.append(Candidate(f"sfR_z{ze}_k{k}", range_only(base), ex))
            for f, s in [(8, 21), (12, 26), (9, 30)]:
                base = lambda d, f=f, s=s: ema(d, fast=f, slow=s)
                out.append(Candidate(f"emaT_{f}_{s}", with_trend(base), ex))
            for ch in (10, 20, 30):
                base = lambda d, ch=ch: donch(d, channel=ch)
                out.append(Candidate(f"donT_{ch}", with_trend(base), ex))
        else:
            for ze in (1.5, 2.0):
                for k in (2, 3):
                    out.append(Candidate(f"sf_z{ze}_k{k}",
                               lambda d, ze=ze, k=k: spike(d, zscore_window=20, lookback_k=k, z_entry=ze), ex))
            for f, s in [(8, 21), (12, 26), (9, 30)]:
                out.append(Candidate(f"ema_{f}_{s}", lambda d, f=f, s=s: ema(d, fast=f, slow=s), ex))
            for ch in (10, 20, 30):
                out.append(Candidate(f"don_{ch}", lambda d, ch=ch: donch(d, channel=ch), ex))
        return out

    def _run():
        df = _provider.get_recent_bars(body.symbol.upper(), body.timeframe, body.bars)
        return walk_forward(df, _cands(), n_folds=body.folds,
                            symbol=body.symbol.upper(), timeframe=body.timeframe)

    try:
        wf = await _a.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}
    if wf.error:
        return {"ok": False, "detail": wf.error}
    return {
        "ok": True, "symbol": wf.symbol, "timeframe": wf.timeframe,
        "regime_filtered": body.regime_filtered, "n_folds": wf.n_folds,
        "avg_is_return": wf.avg_is_return, "avg_oos_return": wf.avg_oos_return,
        "avg_oos_excess": wf.avg_oos_excess, "degradation_pct": wf.degradation_pct,
        "oos_positive_folds": wf.oos_positive_folds, "oos_beat_bh_folds": wf.oos_beat_bh_folds,
        "verdict": wf.verdict,
        "folds": [{"fold": f.fold, "chosen": f.chosen, "is_return_pct": f.is_return_pct,
                   "oos_return_pct": f.oos_return_pct, "oos_buy_hold_pct": f.oos_buy_hold_pct,
                   "oos_excess_pct": f.oos_excess_pct, "oos_trades": f.oos_trades,
                   "oos_start": f.oos_start, "oos_end": f.oos_end} for f in wf.folds],
    }


@app.post("/api/select")
async def select_symbols_endpoint() -> dict:
    """Run regime-filtered walk-forward per M7 symbol; return tradable whitelist."""
    import asyncio as _a

    from ..backtest.selector import select_symbols

    def _run():
        data = {sym: _provider.get_recent_bars(sym, "5m", 3000)
                for sym in _config["universe"]}
        return select_symbols(data, n_folds=4)

    try:
        sel = await _a.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc)}
    return {
        "ok": True, "tradable": sel.tradable, "excluded": sel.excluded,
        "all_avg_oos": sel.all_avg_oos, "tradable_avg_oos": sel.tradable_avg_oos,
        "verdicts": [{"symbol": v.symbol, "tradable": v.tradable,
                      "avg_oos_return": v.avg_oos_return,
                      "oos_beat_bh_folds": v.oos_beat_bh_folds, "n_folds": v.n_folds,
                      "reason": v.reason} for v in sel.verdicts],
    }


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


@app.get("/api/equity_curve")
async def equity_curve(days: int = 7) -> dict:
    """Account equity over time from periodic snapshots (snapshots.enabled)."""
    if _snapshots is None:
        return {"available": False, "detail": "snapshots disabled (snapshots.enabled=false)",
                "points": []}
    # capture one fresh point so the curve is never empty when first viewed
    try:
        _snapshots.capture(_executor, reason="dashboard")
    except Exception:  # noqa: BLE001
        pass
    return {"available": True, "points": _snapshots.equity_curve(days=days)}


@app.post("/api/hooks/{name}")
async def inbound_webhook(name: str, payload: Optional[dict] = None) -> dict:
    """Inbound webhook -> append to the scheduler event log + broadcast.

    Enabled by scheduler.enabled + scheduler.webhooks_enabled. External systems
    (TradingView alerts, etc.) can POST here to drive the platform.
    """
    if _event_log is None or not _config.get("scheduler", {}).get("webhooks_enabled", False):
        return {"ok": False, "detail": "webhooks disabled "
                "(scheduler.enabled + scheduler.webhooks_enabled)"}
    event = _event_log.emit(f"webhook:{name}", payload or {}, source="webhook")
    await hub.broadcast({"type": "webhook", "name": name, "payload": payload or {}})
    return {"ok": True, "event": event}


def _headlines_json(items) -> list:
    return [{"symbol": h.symbol, "headline": h.headline, "summary": h.summary,
             "url": h.url, "created_at": h.created_at.isoformat()} for h in items]


@app.get("/api/news/search")
async def news_search(q: str, symbol: Optional[str] = None, limit: int = 25) -> dict:
    """Keyword search across ALL news sources. Pass `symbol` to include the
    per-symbol sources (Alpaca/Yahoo); RSS is always searched market-wide."""
    import asyncio as _a

    hits = await _a.to_thread(_news_unified.search, q, symbol, limit)
    return {"available": True, "sources": _news_unified.sources(), "query": q,
            "results": _headlines_json(hits)}


@app.get("/api/news/latest")
async def news_latest(symbol: Optional[str] = None, limit: int = 30) -> dict:
    """Newest headlines across all sources, de-duped + ranked. Optional symbol."""
    import asyncio as _a

    items = await _a.to_thread(_news_unified.latest, symbol, limit)
    return {"available": True, "sources": _news_unified.sources(),
            "symbol": symbol, "results": _headlines_json(items)}


class StageBody(BaseModel):
    symbol: str
    side: str
    qty: float = 1
    note: str = ""


class CommitBody(BaseModel):
    message: str


@app.get("/api/orders")
async def orders_list(limit: int = 50) -> dict:
    """Order ledger: every order's stage->commit->push->fill history."""
    recs = _oms.history()[-limit:]
    return {"orders": [{"id": r.id, "state": r.state, "message": r.message,
                        "note": r.note, "request": r.request, "result": r.result,
                        "history": r.history} for r in recs]}


@app.post("/api/orders/stage")
async def orders_stage(body: StageBody) -> dict:
    """Stage an order (recorded, not sent) — the 'git add' of Trading-as-Git."""
    oid = _oms.stage(OrderRequest(symbol=body.symbol.upper(), side=body.side, qty=body.qty),
                     note=body.note)
    await hub.broadcast({"type": "order_staged", "id": oid, "symbol": body.symbol.upper()})
    return {"ok": True, "id": oid}


@app.post("/api/orders/{order_id}/commit")
async def orders_commit(order_id: str, body: CommitBody) -> dict:
    try:
        rec = _oms.commit(order_id, body.message)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "id": rec.id, "state": rec.state}


@app.post("/api/orders/{order_id}/push")
async def orders_push(order_id: str) -> dict:
    """Push (execute) a committed order through guards/risk to the broker."""
    try:
        res = _oms.push(order_id)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}
    await hub.broadcast({"type": "order", "ok": res.ok, "symbol": res.symbol,
                         "side": res.side, "qty": res.qty, "status": res.status,
                         "detail": res.detail})
    return {"ok": res.ok, "status": res.status, "detail": res.detail}


@app.get("/api/config")
async def get_config_view() -> dict:
    """The active behaviour config (config.yaml) for the config-management panel."""
    return {"config": _config}


@app.get("/api/inbox")
async def inbox_list(limit: int = 50) -> dict:
    """Inbox push channel: markdown/docs pushed from the workspace to the user."""
    return {"messages": _inbox[-limit:]}


class InboxBody(BaseModel):
    title: str
    body: str = ""
    kind: str = "markdown"


@app.post("/api/inbox")
async def inbox_push(body: InboxBody) -> dict:
    import datetime as _dt

    msg = {"title": body.title, "body": body.body, "kind": body.kind,
           "ts_utc": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    _inbox.append(msg)
    await hub.broadcast({"type": "inbox", **msg})
    return {"ok": True, "message": msg}


@app.get("/api/universe")
async def universe_view(mode: Optional[str] = None) -> dict:
    """Universe size + source for a given mode (m7|sp500|nasdaq100|sp500_nasdaq100)."""
    from ..universe import universe_info

    cfg = {**_config, "universe_mode": (mode or _config.get("universe_mode", "m7"))}
    return universe_info(cfg)


def _run_scan(mode: Optional[str], top_n: Optional[int]) -> dict:
    """Build the universe + scan it (blocking; call via a thread)."""
    from ..scanner import Scanner
    from ..universe import load_universe

    scfg = _config.get("scanner", {})
    cfg = {**_config, "universe_mode": (mode or _config.get("universe_mode", "m7"))}
    symbols = load_universe(cfg)
    res = Scanner(_provider, _config).scan(
        symbols, timeframe=scfg.get("timeframe", "5m"),
        lookback=scfg.get("lookback", 60), top_n=int(top_n or scfg.get("top_n", 25)),
        min_score=scfg.get("min_score", 0))
    return {"timeframe": res.timeframe, "scanned": res.scanned, "skipped": res.skipped,
            "candidates": res.candidates,
            "note": "score = estimated edge (0-100), NOT a profit guarantee"}


@app.get("/api/scan")
async def scan(mode: Optional[str] = None, top_n: Optional[int] = None) -> dict:
    """Rank the universe by buy-edge score. mode overrides universe_mode for this run."""
    import asyncio as _a

    out = await _a.to_thread(_run_scan, mode, top_n)
    await hub.broadcast({"type": "scan", "scanned": out["scanned"],
                         "n": len(out["candidates"])})
    return out


@app.on_event("startup")
async def _start_scanner_loop() -> None:
    """If scanner.enabled, scan the universe every interval_seconds and broadcast;
    optionally seed the guarded auto-trader with the top candidates."""
    scfg = _config.get("scanner", {})
    if not scfg.get("enabled"):
        return
    import asyncio as _a

    interval = max(30, int(scfg.get("interval_seconds", 300)))

    async def _loop() -> None:
        while True:
            try:
                out = await _a.to_thread(_run_scan, None, None)
                await hub.broadcast({"type": "scan", "scanned": out["scanned"],
                                     "n": len(out["candidates"]),
                                     "candidates": out["candidates"][:10]})
                if (scfg.get("feed_auto_trader")
                        and _config.get("auto_trader", {}).get("enabled")
                        and _llm is not None):
                    from ..agent.auto_trader import AutoTrader
                    from ..mcp.tools import Toolset

                    syms = [c["symbol"] for c in out["candidates"]]
                    ts = Toolset(_executor, oms=_oms, market_data=None, config=_config)
                    trader = AutoTrader(ts, _llm, _config.get("auto_trader", {}),
                                        news=_news_unified)
                    await _a.to_thread(trader.run_cycle, syms)
            except Exception:  # noqa: BLE001 - a scan hiccup must not kill the loop
                pass
            await _a.sleep(interval)

    _a.create_task(_loop())


@app.post("/api/agent/auto/cycle")
async def auto_trader_cycle() -> dict:
    """Run ONE autonomous decision cycle. Gated by auto_trader.enabled; dry-run by
    default (proposes only). Any execution routes through the OMS + guards + risk."""
    acfg = _config.get("auto_trader", {})
    if not acfg.get("enabled", False):
        return {"ran": False, "detail": "auto_trader disabled (auto_trader.enabled=false)"}
    if _llm is None:
        return {"ran": False, "detail": "no LLM provider (start Ollama or set a key)"}
    import asyncio as _a

    from ..agent.auto_trader import AutoTrader
    from ..mcp.tools import Toolset

    toolset = Toolset(_executor, oms=_oms, market_data=None, config=_config)
    trader = AutoTrader(toolset, _llm, acfg, news=_news_unified)
    out = await _a.to_thread(trader.run_cycle)
    await hub.broadcast({"type": "auto_cycle", "dry_run": out.get("dry_run", True),
                         "n": out.get("n_proposed", 0)})
    return out


class ReportBody(BaseModel):
    kind: str               # backtest | walkforward | committee
    format: str = "md"      # md | docx | pdf
    data: dict              # the result payload (as returned by /api/backtest etc.)


@app.post("/api/report")
async def report(body: ReportBody):
    """Render a result to Markdown (text) or Word/PDF (file download)."""
    from fastapi.responses import PlainTextResponse

    from ..report.exporter import export_report

    try:
        content, media, is_file = export_report(body.kind, body.data, body.format)
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    except ImportError:
        return {"ok": False, "detail": f"{body.format} needs python-docx/reportlab installed"}
    if is_file:
        return FileResponse(str(content), media_type=media,
                            filename=Path(content).name)
    return PlainTextResponse(content, media_type=media)


@app.get("/api/reflections")
async def reflections(symbol: Optional[str] = None, limit: int = 20) -> dict:
    """Lessons learned from closed trades (reflection.enabled)."""
    rcfg = _config.get("reflection", {})
    if not rcfg.get("enabled", False):
        return {"available": False, "detail": "reflection disabled (reflection.enabled=false)",
                "notes": []}
    from ..research.reflection import ReflectionMemory

    mem = ReflectionMemory(max_notes=rcfg.get("max_notes", 200))
    return {"available": True, "notes": mem.recent(symbol=symbol, limit=limit)}


@app.get("/api/exec/analytics")
async def exec_analytics() -> dict:
    """Transaction-cost analysis: per-order slippage vs arrival + aggregate summary."""
    return {"summary": _exec_analytics.summary(),
            "recent": _exec_analytics._read()[-50:]}


@app.get("/api/options/greeks")
async def options_greeks(spot: float, strike: float, days: float, vol: float,
                         rate: float = 0.0, call: bool = True) -> dict:
    """Black-Scholes price + Greeks (local, offline). vol as a decimal (0.25 = 25%),
    days to expiry. gs-quant is used only if installed + Marquee-authed; otherwise
    this is local BS and labels source accordingly."""
    from ..research.gs_analytics import OptionsAnalytics

    g = OptionsAnalytics().greeks(spot=spot, strike=strike, t_years=days / 365.0,
                                  vol=vol, rate=rate, is_call=call)
    return {"ok": True, **g.as_dict()}


@app.get("/api/perspective/status")
async def perspective_status() -> dict:
    """Whether the Perspective streaming feed is live (enabled + package present).

    Pure read — no executor/snapshot access — so it leaks nothing and has no side
    effects. The snapshot refresh happens on the authenticated WS connect instead.
    """
    if _perspective is None:
        return {"available": False,
                "detail": "disabled (perspective.enabled=false or perspective not installed)"}
    return {"available": True, "tables": list(_perspective._tables.keys()),
            "websocket": "/ws/perspective"}


@app.websocket("/ws/perspective")
async def perspective_ws(ws: WebSocket) -> None:
    """Perspective protocol socket — perspective-viewer clients connect here."""
    if _perspective is None:
        await ws.close(code=1011)
        return
    if not _ws_origin_ok(ws):
        await ws.close(code=1008)  # cross-site origin — reject the handshake
        return
    # Refresh snapshot-style tables on connect (after the origin check), so a
    # freshly opened viewer isn't empty without exposing data on an open GET.
    try:
        _perspective.replace("positions", _executor.list_positions())
        if _snapshots is not None:
            _perspective.replace("equity_curve", _snapshots.equity_curve())
    except Exception:  # noqa: BLE001
        pass
    await _perspective.handler(ws).run()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    if not _ws_origin_ok(ws):
        await ws.close(code=1008)  # cross-site origin — reject the handshake
        return
    await hub.connect(ws)
    try:
        await ws.send_text(json.dumps({"type": "hello", "universe": _config["universe"]}))
        while True:
            await ws.receive_text()  # keepalive; client doesn't need to send
    except WebSocketDisconnect:
        hub.disconnect(ws)
