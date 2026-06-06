"""Perspective feed tests — the event->row mapping is pure (no perspective dep).

The PerspectiveFeed itself degrades to available=False when perspective isn't
installed, so we assert that path too rather than requiring the optional package.
"""
from backend.web.perspective_server import SCHEMAS, PerspectiveFeed, row_for_event


def test_signal_event_maps_to_signals_row():
    table, row = row_for_event({
        "type": "signal", "ts_utc": "t", "symbol": "AAPL", "strategy": "spike_fade",
        "side": "buy", "strength": 0.8, "close": 100.5, "regime": "range"})
    assert table == "signals"
    assert row["symbol"] == "AAPL" and row["strength"] == 0.8
    assert set(row.keys()) == set(SCHEMAS["signals"].keys())


def test_order_event_maps_to_orders_row():
    table, row = row_for_event({
        "type": "order", "symbol": "MSFT", "side": "sell", "qty": 3,
        "status": "filled", "fill_price": 410.2, "detail": "ok"})
    assert table == "orders"
    assert row["qty"] == 3.0 and row["fill_price"] == 410.2
    assert set(row.keys()) == set(SCHEMAS["orders"].keys())


def test_unmapped_events_ignored():
    assert row_for_event({"type": "price", "symbol": "AAPL", "close": 1}) is None
    assert row_for_event({"type": "inbox", "title": "x"}) is None


def test_feed_degrades_without_perspective():
    feed = PerspectiveFeed()
    # perspective may or may not be installed; either way these must not raise
    feed.feed({"type": "signal", "symbol": "AAPL", "side": "buy"})
    feed.replace("positions", [{"symbol": "AAPL"}])
    assert isinstance(feed.available, bool)
