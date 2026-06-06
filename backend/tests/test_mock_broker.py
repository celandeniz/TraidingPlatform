"""MockBroker tests — deterministic, no network."""
from backend.execution.base import OrderRequest
from backend.execution.mock_adapter import MockExecutionAdapter


def _buy(sym, qty, price=None, **kw):
    meta = {"price": price} if price is not None else {}
    return OrderRequest(sym, "buy", qty, meta=meta, **kw)


def _sell(sym, qty, price=None, **kw):
    meta = {"price": price} if price is not None else {}
    return OrderRequest(sym, "sell", qty, meta=meta, **kw)


def test_buy_opens_long_and_debits_cash():
    b = MockExecutionAdapter(starting_cash=10_000)
    r = b.submit(_buy("AAPL", 10, price=100))
    assert r.ok and r.status == "filled"
    pos = b.list_positions()
    assert len(pos) == 1
    assert pos[0]["symbol"] == "AAPL" and pos[0]["side"] == "long" and pos[0]["qty"] == 10
    assert b.account_summary()["cash"] == 9_000  # 10_000 - 10*100


def test_unrealized_pl_tracks_mark():
    b = MockExecutionAdapter(starting_cash=10_000)
    b.submit(_buy("AAPL", 10, price=100))
    b.mark("AAPL", 110)
    pos = b.list_positions()[0]
    assert pos["unrealized_pl"] == 100  # (110-100)*10
    assert round(pos["unrealized_plpc"], 4) == 10.0
    assert b.account_summary()["equity"] == 10_100  # cash 9000 + mark value


def test_short_position_pl_is_inverse():
    b = MockExecutionAdapter(starting_cash=10_000)
    b.submit(_sell("BTC/USDT", 2, price=100))
    pos = b.list_positions()[0]
    assert pos["side"] == "short" and pos["qty"] == 2
    b.mark("BTC/USDT", 90)
    assert b.list_positions()[0]["unrealized_pl"] == 20  # short gains as price falls


def test_averaging_into_long():
    b = MockExecutionAdapter()
    b.submit(_buy("X", 10, price=100))
    b.submit(_buy("X", 10, price=120))
    pos = b.list_positions()[0]
    assert pos["qty"] == 20
    assert pos["avg_entry"] == 110  # (100*10 + 120*10)/20


def test_reduce_only_cannot_open_or_flip():
    b = MockExecutionAdapter()
    # reduce_only with no position -> reject
    r = b.submit(_sell("X", 5, price=100, reduce_only=True))
    assert not r.ok and "reduce" in r.detail
    # open a long, then a reduce-only sell larger than the position only closes it
    b.submit(_buy("X", 10, price=100))
    b.submit(_sell("X", 50, price=100, reduce_only=True))
    assert b.list_positions() == []  # fully closed, never flipped short


def test_closing_long_returns_cash_and_clears_position():
    b = MockExecutionAdapter(starting_cash=10_000)
    b.submit(_buy("X", 10, price=100))   # cash 9000
    b.submit(_sell("X", 10, price=130))  # cash 9000 + 1300
    assert b.list_positions() == []
    assert b.account_summary()["cash"] == 10_300


def test_no_price_rejects():
    b = MockExecutionAdapter()
    r = b.submit(OrderRequest("X", "buy", 1))  # no mark, no meta price
    assert not r.ok and "no price" in r.detail
