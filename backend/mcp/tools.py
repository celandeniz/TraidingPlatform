"""Toolset — the platform capabilities exposed over MCP, as plain dict-returning
methods so they're unit-testable without the MCP SDK or a network.

submit_order routes through the OMS (stage->commit->push) so every agent-driven
order is auditable and still passes whatever guard/risk layer wraps the executor.
Read tools (positions, account, recent signals, market data, fundamentals) are
defensive: a missing dependency or provider hiccup degrades to an informative
dict rather than raising into the agent.
"""
from __future__ import annotations

import json
from typing import Optional

from ..execution.base import ExecutionAdapter, OrderRequest
from ..settings import REPO_DIR


class Toolset:
    def __init__(self, executor: ExecutionAdapter, *, oms=None, market_data=None,
                 config: Optional[dict] = None):
        self._executor = executor
        self._oms = oms                  # OrderManager | None
        self._md = market_data           # MarketDataProvider | None
        self._config = config or {}

    # --- account / positions ----------------------------------------------
    def list_positions(self) -> dict:
        try:
            return {"ok": True, "positions": self._executor.list_positions()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc), "positions": []}

    def account_summary(self) -> dict:
        try:
            return {"ok": True, "account": self._executor.account_summary()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    # --- orders (auditable via OMS) ----------------------------------------
    def submit_order(self, symbol: str, side: str, qty: float,
                     reduce_only: bool = False, message: str = "via MCP") -> dict:
        if side not in ("buy", "sell"):
            return {"ok": False, "detail": "side must be 'buy' or 'sell'"}
        req = OrderRequest(symbol=symbol.upper(), side=side, qty=float(qty),
                           reduce_only=reduce_only)
        if self._oms is not None:
            res = self._oms.stage_commit_push(req, message=message, note="mcp")
        else:
            res = self._executor.submit(req)
        return {"ok": res.ok, "order_id": res.order_id, "symbol": res.symbol,
                "side": res.side, "qty": res.qty, "status": res.status,
                "detail": res.detail}

    def order_history(self, limit: int = 50) -> dict:
        if self._oms is None:
            return {"ok": False, "detail": "OMS not configured", "orders": []}
        recs = self._oms.history()[-limit:]
        return {"ok": True, "orders": [
            {"id": r.id, "state": r.state, "message": r.message,
             "request": r.request, "result": r.result} for r in recs]}

    # --- signals (from the JSONL tape) -------------------------------------
    def recent_signals(self, limit: int = 20) -> dict:
        """Most recent signal-tape entries across today's logs."""
        log_dir = REPO_DIR / "logs"
        tapes = sorted(log_dir.glob("tape_*.jsonl"))
        if not tapes:
            return {"ok": True, "signals": [], "detail": "no tape yet"}
        lines: list[dict] = []
        with open(tapes[-1], "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"ok": True, "signals": lines[-limit:]}

    # --- market data / research --------------------------------------------
    def get_market_data(self, symbol: str, timeframe: str = "1d", bars: int = 100,
                        kind: str = "equity") -> dict:
        if self._md is None:
            return {"ok": False, "detail": "market data disabled (marketdata.enabled=false)"}
        try:
            df = self._md.get_recent_bars(symbol.upper(), timeframe, bars, kind=kind)
            return {"ok": True, "symbol": symbol.upper(), "timeframe": timeframe,
                    "bars": df.reset_index().to_dict(orient="records")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    def get_fundamentals(self, symbol: str) -> dict:
        if self._md is None:
            return {"ok": False, "detail": "market data disabled (marketdata.enabled=false)"}
        try:
            f = self._md.get_fundamentals(symbol.upper())
            return {"ok": True, "symbol": f.symbol, "name": f.name, "sector": f.sector,
                    "industry": f.industry, "market_cap": f.market_cap,
                    "pe_ratio": f.pe_ratio, "debt_to_equity": f.debt_to_equity,
                    "profit_margin": f.profit_margin}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    def search_symbols(self, query: str) -> dict:
        if self._md is None:
            return {"ok": False, "detail": "market data disabled (marketdata.enabled=false)"}
        try:
            matches = self._md.search_symbols(query)
            return {"ok": True, "matches": [
                {"symbol": m.symbol, "name": m.name, "kind": m.kind,
                 "exchange": m.exchange} for m in matches]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    def run_backtest(self, symbol: str, timeframe: str = "5m", strategy: str = "spike_fade",
                     bars: int = 2000) -> dict:
        """Run one no-lookahead backtest on recent bars (needs a data provider)."""
        try:
            from ..backtest.engine import CostModel, ExitParams, run_backtest
            from ..brokers import build_data_provider
            from ..settings import get_settings
            from ..strategy.donchian_breakout import generate as donch
            from ..strategy.ema_momentum import generate as ema
            from ..strategy.spike_fade import generate as spike

            fns = {
                "spike_fade": lambda df: spike(df, zscore_window=20, lookback_k=2, z_entry=2.0),
                "ema_momentum": lambda df: ema(df, fast=12, slow=26),
                "donchian": lambda df: donch(df, channel=20),
            }
            fn = fns.get(strategy, fns["spike_fade"])
            provider = build_data_provider("equity", get_settings(), self._config)
            df = provider.get_recent_bars(symbol.upper(), timeframe, bars)
            res = run_backtest(df, fn, exits=ExitParams(2.0, 1.5, 0.8, 90, True),
                               costs=CostModel(1.0, 2.0), warmup=35,
                               scenario=f"{symbol}|{timeframe}|{strategy}")
            return {"ok": True, "symbol": symbol.upper(), "strategy": strategy,
                    "n_trades": res.n_trades, "win_rate": round(res.win_rate, 1),
                    "total_return_pct": round(res.total_return_pct, 2),
                    "sharpe": res.sharpe, "max_drawdown_pct": round(res.max_drawdown_pct, 1),
                    "significant": res.significant, "p_value": res.p_value}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    # --- introspection -----------------------------------------------------
    def describe(self) -> dict:
        """List the tool names this set exposes (for discovery/tests)."""
        return {"tools": ["list_positions", "account_summary", "submit_order",
                          "order_history", "recent_signals", "get_market_data",
                          "get_fundamentals", "search_symbols", "run_backtest"]}
