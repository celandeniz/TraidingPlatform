"""Broker selection / routing — keeps the engine and dashboard broker-agnostic.

resolve_asset_class() maps a symbol to equity|crypto via config. build_*()
factories construct the right DataProvider / ExecutionAdapter. The
RoutingExecutionAdapter holds one of each and fans out by asset_class so the
dashboard keeps a single executor object whose submit/list_positions/
account_summary work across both brokers.
"""
from __future__ import annotations

from .execution.base import AssetClass, ExecutionAdapter, OrderRequest, OrderResult, PositionView


def resolve_asset_class(symbol: str, cfg: dict) -> AssetClass:
    brokers = cfg.get("brokers", {})
    overrides = brokers.get("symbol_overrides", {}) or {}
    if symbol in overrides:
        return overrides[symbol]
    # Crypto symbols are pair-formatted (e.g. BTC/USDT); equities are not.
    if "/" in symbol:
        return "crypto"
    return brokers.get("default_asset_class", "equity")


def build_data_provider(asset_class: AssetClass, settings, cfg: dict):
    if asset_class == "crypto":
        from .data.ccxt_provider import CcxtDataProvider

        c = cfg.get("brokers", {}).get("crypto", {})
        return CcxtDataProvider(
            exchange=getattr(settings, "ccxt_exchange", c.get("exchange", "binance")),
            api_key=getattr(settings, "ccxt_api_key", ""),
            api_secret=getattr(settings, "ccxt_api_secret", ""),
            sandbox=c.get("sandbox", True),
        )
    from .data.alpaca_provider import AlpacaProvider

    return AlpacaProvider(settings.alpaca_api_key, settings.alpaca_api_secret,
                          feed=settings.alpaca_data_feed)


def build_executor(asset_class: AssetClass, settings, cfg: dict) -> ExecutionAdapter:
    """Construct a single-broker executor (paper/sandbox by default).

    Live adapters are built only in execution/live.py and only when LIVE_TRADING
    is set; the factory there always wraps them in a RiskManager.

    Set ``brokers.executor: mock`` (or ``brokers.<asset_class>.executor: mock``)
    in config.yaml to use the in-memory MockBroker — no network, deterministic
    fills, useful for offline demos and CI.
    """
    brokers = cfg.get("brokers", {})
    # Per-asset-class executor override (default: alpaca paper for equity, ccxt for crypto).
    executor = brokers.get(asset_class, {}).get("executor") or brokers.get("executor")
    if executor == "mock":
        from .execution.mock_adapter import MockExecutionAdapter

        m = brokers.get("mock", {})
        return MockExecutionAdapter(
            starting_cash=float(m.get("starting_cash", 100_000)),
            asset_class=asset_class,
        )
    if executor == "ib":
        from .execution.ib_adapter import IBExecutionAdapter

        ib = brokers.get("ib", {})
        return IBExecutionAdapter(
            host=ib.get("host", "127.0.0.1"),
            port=int(ib.get("port", 7497)),
            client_id=int(ib.get("client_id", 1)),
            account=ib.get("account", ""),
        )
    if asset_class == "crypto":
        from .execution.ccxt_adapter import CcxtExecutionAdapter

        c = cfg.get("brokers", {}).get("crypto", {})
        return CcxtExecutionAdapter(
            exchange=getattr(settings, "ccxt_exchange", c.get("exchange", "binance")),
            api_key=getattr(settings, "ccxt_api_key", ""),
            api_secret=getattr(settings, "ccxt_api_secret", ""),
            sandbox=c.get("sandbox", True),
            default_leverage=c.get("leverage", 1),
        )
    from .execution.paper import PaperExecutionAdapter

    return PaperExecutionAdapter(settings.alpaca_api_key, settings.alpaca_api_secret)


class RoutingExecutionAdapter:
    """Fans out to per-asset-class executors. Implements ExecutionAdapter."""

    def __init__(self, executors: dict[AssetClass, ExecutionAdapter]):
        self._executors = executors  # {"equity": ..., "crypto": ...}

    def _for(self, asset_class: AssetClass) -> ExecutionAdapter | None:
        return self._executors.get(asset_class)

    def submit(self, req: OrderRequest) -> OrderResult:
        ex = self._for(req.asset_class)
        if ex is None:
            return OrderResult(False, None, req.symbol, req.side, req.qty,
                               "rejected", f"no executor for {req.asset_class}")
        return ex.submit(req)

    def list_positions(self) -> list[PositionView]:
        out: list[PositionView] = []
        for ex in self._executors.values():
            try:
                out.extend(ex.list_positions())
            except Exception:  # noqa: BLE001 - one broker down shouldn't blank the view
                continue
        return out

    def account_summary(self) -> dict:
        summaries = {}
        for ac, ex in self._executors.items():
            try:
                summaries[ac] = ex.account_summary()
            except Exception as exc:  # noqa: BLE001
                summaries[ac] = {"status": "error", "detail": str(exc)}
        # Merge: sum equity/cash across brokers, keep per-broker breakdown.
        equity = sum(float(s.get("equity", 0) or 0) for s in summaries.values())
        cash = sum(float(s.get("cash", 0) or 0) for s in summaries.values())
        return {"status": "active", "equity": equity, "cash": cash,
                "buying_power": cash, "by_broker": summaries}


def build_routing_executor(settings, cfg: dict, *, asset_classes=None) -> RoutingExecutionAdapter:
    """Build a RoutingExecutionAdapter over the requested asset classes.

    Defaults to equity only (current behavior) unless crypto symbols/overrides
    indicate crypto is in use.
    """
    if asset_classes is None:
        asset_classes = ["equity"]
        overrides = cfg.get("brokers", {}).get("symbol_overrides", {}) or {}
        if any(v == "crypto" for v in overrides.values()):
            asset_classes.append("crypto")
    executors = {}
    for ac in asset_classes:
        try:
            executors[ac] = build_executor(ac, settings, cfg)
        except Exception:  # noqa: BLE001 - missing crypto keys shouldn't break equity
            continue
    return RoutingExecutionAdapter(executors)
