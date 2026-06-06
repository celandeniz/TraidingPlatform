"""FillModel tests — pure, deterministic."""
from backend.execution.base import OrderRequest
from backend.execution.fills import FillModelConfig, Quote, simulate_fill

CFG = FillModelConfig(spread_bps=2.0, base_slippage_bps=1.0, impact_coef_bps=50.0,
                      max_participation=1.0, commission_bps=1.0)


def test_market_buy_fills_adversely_higher():
    req = OrderRequest("AAPL", "buy", 10, order_type="market")
    r = simulate_fill(req, Quote(ref_price=100.0), CFG)
    # half-spread(1) + base(1) + commission(1) = 3 bps, no volume -> no impact
    assert r.filled and r.reason == "filled"
    assert r.slippage_bps == 3.0
    assert round(r.fill_price, 4) == round(100.0 * (1 + 3e-4), 4)


def test_market_sell_fills_adversely_lower():
    r = simulate_fill(OrderRequest("AAPL", "sell", 10), Quote(ref_price=100.0), CFG)
    assert round(r.fill_price, 4) == round(100.0 * (1 - 3e-4), 4)


def test_limit_buy_only_fills_when_crossed():
    req = OrderRequest("AAPL", "buy", 1, order_type="limit", limit_price=99.0)
    # market low 99.5 never reaches the 99 limit -> no fill
    assert simulate_fill(req, Quote(ref_price=100, high=100.5, low=99.5), CFG).reason == "no_cross"
    # market dips to 98.5 -> crosses 99 -> fills at the limit (+ costs)
    r = simulate_fill(req, Quote(ref_price=100, high=100.5, low=98.5), CFG)
    assert r.filled and round(r.fill_price, 4) == round(99.0 * (1 + 3e-4), 4)


def test_stop_buy_triggers_only_above_stop():
    req = OrderRequest("AAPL", "buy", 1, order_type="stop", stop_price=101.0)
    assert simulate_fill(req, Quote(ref_price=100, high=100.5, low=99.5), CFG).reason == "not_triggered"
    r = simulate_fill(req, Quote(ref_price=100.2, high=101.2, low=99.8), CFG)
    assert r.filled  # high 101.2 >= stop 101 -> triggered, fills at ref


def test_partial_fill_caps_at_participation():
    cfg = FillModelConfig(spread_bps=0, base_slippage_bps=0, impact_coef_bps=0,
                          max_participation=0.5, commission_bps=0)
    req = OrderRequest("X", "buy", 1000)
    r = simulate_fill(req, Quote(ref_price=10, volume=1000), cfg)
    assert r.reason == "partial" and r.filled_qty == 500  # 0.5 * 1000


def test_impact_scales_with_participation():
    cfg = FillModelConfig(spread_bps=0, base_slippage_bps=0, impact_coef_bps=100,
                          max_participation=1.0, commission_bps=0)
    small = simulate_fill(OrderRequest("X", "buy", 10), Quote(ref_price=10, volume=1000), cfg)
    big = simulate_fill(OrderRequest("X", "buy", 500), Quote(ref_price=10, volume=1000), cfg)
    assert big.slippage_bps > small.slippage_bps  # 50% participation costs more than 1%
