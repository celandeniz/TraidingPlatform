"""Options analytics tests — local Black-Scholes, no network/auth."""
import math

from backend.research.gs_analytics import OptionsAnalytics, black_scholes_greeks


def test_atm_call_delta_near_half():
    g = black_scholes_greeks(spot=100, strike=100, t_years=1.0, vol=0.2, rate=0.0, is_call=True)
    assert 0.5 < g.delta < 0.58   # ATM call delta is just above 0.5
    assert g.price > 0 and g.gamma > 0 and g.vega > 0
    assert g.source == "local_bs"


def test_put_call_parity():
    # C - P = S*e^{-qT} - K*e^{-rT}; with q=0: C - P = S - K e^{-rT}
    s, k, t, v, r = 100, 95, 0.5, 0.25, 0.03
    c = black_scholes_greeks(s, k, t, v, r, is_call=True).price
    p = black_scholes_greeks(s, k, t, v, r, is_call=False).price
    assert abs((c - p) - (s - k * math.exp(-r * t))) < 1e-3


def test_call_and_put_delta_signs():
    c = black_scholes_greeks(100, 100, 0.5, 0.2, is_call=True)
    p = black_scholes_greeks(100, 100, 0.5, 0.2, is_call=False)
    assert c.delta > 0 and p.delta < 0
    assert abs(c.delta - p.delta - 1.0) < 1e-6   # call delta - put delta = 1 (q=0)


def test_degenerate_inputs_return_intrinsic():
    g = black_scholes_greeks(spot=110, strike=100, t_years=0.0, vol=0.2, is_call=True)
    assert g.price == 10.0 and g.gamma == 0.0  # expired ITM call = intrinsic


def test_analytics_reports_source():
    oa = OptionsAnalytics()
    g = oa.greeks(spot=100, strike=100, t_years=0.25, vol=0.3)
    assert g.source == "local_bs"            # honest: no Marquee auth
    assert isinstance(oa.gs_quant_available, bool)
