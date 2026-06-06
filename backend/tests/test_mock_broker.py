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


# --- realistic mode (FillModel) ---------------------------------------------

def test_realistic_market_fill_includes_slippage_and_reports_fill():
    b = MockExecutionAdapter(realistic=True)
    b.mark("AAPL", 100)
    r = b.submit(OrderRequest("AAPL", "buy", 10, order_type="market"))
    assert r.ok and r.status == "filled" and r.filled_qty == 10
    assert r.fill_price > 100  # adverse: buy fills above ref


def test_realistic_limit_not_filled_when_not_crossed():
    b = MockExecutionAdapter(realistic=True)
    b.mark("AAPL", 100)
    # buy-limit at 99 with market at 100 -> not crossed (mock high=low=ref)
    r = b.submit(OrderRequest("AAPL", "buy", 1, order_type="limit", limit_price=99.0))
    assert not r.ok and "not filled" in r.detail
    assert b.list_positions() == []


def test_realistic_limit_fills_when_price_reaches_limit():
    b = MockExecutionAdapter(realistic=True)
    b.mark("AAPL", 99)  # market down at 99 -> buy-limit 99 crosses
    r = b.submit(OrderRequest("AAPL", "buy", 1, order_type="limit", limit_price=99.0))
    assert r.ok and r.filled_qty == 1


def test_realistic_partial_fill_caps_at_participation():
    from backend.execution.fills import FillModelConfig

    b = MockExecutionAdapter(realistic=True,
                             fill_config=FillModelConfig(max_participation=0.25))
    b.mark("X", 10)
    r = b.submit(OrderRequest("X", "buy", 1000, meta={"volume": 1000}))
    assert r.status == "partial" and r.filled_qty == 250
    assert b.list_positions()[0]["qty"] == 250
