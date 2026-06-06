"""Snapshot store + equity curve — no network (MockBroker)."""
from datetime import datetime, timezone

from backend.execution.base import OrderRequest
from backend.execution.mock_adapter import MockExecutionAdapter
from backend.portfolio.snapshots import SnapshotStore

UTC = timezone.utc


def test_capture_writes_and_equity_curve_reads_back(tmp_path):
    b = MockExecutionAdapter(starting_cash=10_000)
    b.mark("AAPL", 100)
    times = iter([datetime(2024, 1, 1, 14, 0, tzinfo=UTC),
                  datetime(2024, 1, 1, 14, 5, tzinfo=UTC)])
    store = SnapshotStore(directory=tmp_path, clock=lambda: next(times))

    s1 = store.capture(b, reason="open")
    assert s1["equity"] == 10_000 and s1["open_positions"] == 0

    b.submit(OrderRequest("AAPL", "buy", 10))  # cash 9000, +1000 holdings
    b.mark("AAPL", 110)                          # equity 10_100
    s2 = store.capture(b, reason="periodic")
    assert s2["open_positions"] == 1 and s2["equity"] == 10_100

    curve = store.equity_curve()
    assert [round(p["equity"]) for p in curve] == [10_000, 10_100]


def test_equity_curve_empty_when_no_snapshots(tmp_path):
    store = SnapshotStore(directory=tmp_path)
    assert store.equity_curve() == []
