"""Live-mode gating tests — no network, no real broker calls."""
import pytest

from backend.execution.base import OrderRequest
from backend.execution.live import (
    AlpacaLiveExecutionAdapter, LiveTradingDisabled, build_live_executor,
)


class _Settings:
    live_trading = False
    alpaca_api_key = "k"
    alpaca_api_secret = "s"
    ccxt_exchange = "binance"
    ccxt_api_key = ""
    ccxt_api_secret = ""


def test_live_adapter_refuses_without_flag():
    with pytest.raises(LiveTradingDisabled):
        AlpacaLiveExecutionAdapter("k", "s", live_trading=False)


def test_build_live_executor_refuses_without_flag():
    with pytest.raises(LiveTradingDisabled):
        build_live_executor("equity", _Settings(), {}, confirm=lambda r: True)


def test_confirm_callback_blocks_unconfirmed(monkeypatch):
    import alpaca.trading.client as tc

    class FakeClient:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(tc, "TradingClient", FakeClient)
    adapter = AlpacaLiveExecutionAdapter("k", "s", live_trading=True,
                                         confirm=lambda req: False)
    r = adapter.submit(OrderRequest("AAPL", "buy", 1))
    assert not r.ok and r.status == "unconfirmed"
