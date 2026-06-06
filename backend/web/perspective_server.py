"""Perspective (JPMorgan/FINOS) streaming tables for the dashboard.

Hosts a Perspective ``Server`` with named ``Table``s (signals, orders, positions,
exec_quality, equity_curve) that browser ``perspective-viewer`` clients connect to
over a WebSocket — the same real-time analytics grid JPMorgan traders use, free.

The platform's existing ``Hub`` events are forwarded here via ``feed()``; the
event->row mapping (``row_for_event``) is a pure function so it's unit-testable
without the perspective package installed. ``perspective`` is imported lazily;
if it's absent, ``PerspectiveFeed.available`` is False and the app skips the route.

Clean-room: written against the public perspective-python API.
"""
from __future__ import annotations

from typing import Optional

# Table schemas (perspective type strings). Kept here so they're inspectable in tests.
SCHEMAS = {
    "signals": {"ts_utc": "string", "symbol": "string", "strategy": "string",
                "side": "string", "strength": "float", "close": "float",
                "regime": "string"},
    "orders": {"ts_utc": "string", "symbol": "string", "side": "string",
               "qty": "float", "status": "string", "fill_price": "float",
               "detail": "string"},
    "positions": {"symbol": "string", "side": "string", "qty": "float",
                  "avg_entry": "float", "current": "float", "unrealized_pl": "float"},
    "exec_quality": {"ts_utc": "string", "symbol": "string", "side": "string",
                     "slippage_bps": "float", "fill_ratio": "float", "status": "string"},
    "equity_curve": {"ts_utc": "string", "equity": "float", "cash": "float"},
}


def row_for_event(event: dict) -> Optional[tuple]:
    """Map a Hub broadcast event to (table_name, row_dict), or None to ignore.

    Pure — no perspective import — so the routing logic is testable standalone.
    """
    t = event.get("type")
    if t == "signal":
        return "signals", {
            "ts_utc": str(event.get("ts_utc", "")), "symbol": event.get("symbol", ""),
            "strategy": event.get("strategy", ""), "side": event.get("side", ""),
            "strength": float(event.get("strength", 0) or 0),
            "close": float(event.get("close", 0) or 0), "regime": event.get("regime", ""),
        }
    if t == "order":
        return "orders", {
            "ts_utc": str(event.get("ts_utc", "")), "symbol": event.get("symbol", ""),
            "side": event.get("side", ""), "qty": float(event.get("qty", 0) or 0),
            "status": event.get("status", ""),
            "fill_price": float(event.get("fill_price", 0) or 0),
            "detail": event.get("detail", ""),
        }
    return None


class PerspectiveFeed:
    """Owns the Perspective Server + named tables and feeds them from Hub events."""

    def __init__(self):
        self.available = False
        self._server = None
        self._client = None
        self._tables = {}
        try:
            from perspective import Server  # lazy: optional dependency
        except Exception:  # noqa: BLE001 - perspective not installed -> stay disabled
            return
        self._server = Server()
        self._client = self._server.new_local_client()
        for name, schema in SCHEMAS.items():
            self._tables[name] = self._client.table(schema, name=name, limit=5000)
        self.available = True

    @property
    def server(self):
        return self._server

    def feed(self, event: dict) -> None:
        """Forward one Hub event to the matching table (no-op if unmapped/disabled)."""
        if not self.available:
            return
        mapped = row_for_event(event)
        if mapped is None:
            return
        name, row = mapped
        try:
            self._tables[name].update([row])
        except Exception:  # noqa: BLE001 - a viz hiccup must never break trading
            pass

    def replace(self, table: str, rows: list) -> None:
        """Replace the contents of a snapshot-style table (positions/equity/tca)."""
        if not self.available or table not in self._tables or not rows:
            return
        try:
            self._tables[table].update(rows)
        except Exception:  # noqa: BLE001
            pass

    def handler(self, websocket):
        """Build the Starlette/FastAPI websocket handler bound to this server."""
        from perspective.handlers.starlette import PerspectiveStarletteHandler

        return PerspectiveStarletteHandler(perspective_server=self._server,
                                           websocket=websocket)
