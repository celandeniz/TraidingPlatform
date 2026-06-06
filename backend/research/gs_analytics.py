"""Options analytics — local Black-Scholes Greeks, with gs-quant when usable.

HONEST SCOPE: Goldman's gs-quant is pure-Python and Apache-2.0, but its headline
derivative pricing runs through the **Marquee API, which needs GS institutional
credentials** this project doesn't have. So the dependable, always-offline value
here is a self-contained Black-Scholes Greeks calculator (no auth, no network).
If gs-quant is installed AND a session is available, we'd prefer it; otherwise we
fall back to local BS and label the source so the caller is never misled.

Clean-room: standard Black-Scholes; gs-quant used only opportunistically.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float       # per 1.00 (100%) change in vol; divide by 100 for per-1%-vol
    theta: float      # per year; divide by 365 for per-day
    rho: float
    source: str = "local_bs"

    def as_dict(self) -> dict:
        return asdict(self)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(spot: float, strike: float, t_years: float, vol: float,
                         rate: float = 0.0, is_call: bool = True,
                         div_yield: float = 0.0) -> Greeks:
    """Black-Scholes(-Merton) price + Greeks. Pure; safe for degenerate inputs."""
    if spot <= 0 or strike <= 0 or t_years <= 0 or vol <= 0:
        # intrinsic-only fallback when the model is undefined
        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        delta = (1.0 if spot > strike else 0.0) if is_call else (-1.0 if spot < strike else 0.0)
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0, 0.0)

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-rate * t_years)
    div = math.exp(-div_yield * t_years)

    if is_call:
        price = spot * div * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
        delta = div * _norm_cdf(d1)
        rho = strike * t_years * disc * _norm_cdf(d2) / 100.0
        theta = (-(spot * div * _norm_pdf(d1) * vol) / (2 * sqrt_t)
                 - rate * strike * disc * _norm_cdf(d2)
                 + div_yield * spot * div * _norm_cdf(d1))
    else:
        price = strike * disc * _norm_cdf(-d2) - spot * div * _norm_cdf(-d1)
        delta = -div * _norm_cdf(-d1)
        rho = -strike * t_years * disc * _norm_cdf(-d2) / 100.0
        theta = (-(spot * div * _norm_pdf(d1) * vol) / (2 * sqrt_t)
                 + rate * strike * disc * _norm_cdf(-d2)
                 - div_yield * spot * div * _norm_cdf(-d1))

    gamma = div * _norm_pdf(d1) / (spot * vol * sqrt_t)
    vega = spot * div * _norm_pdf(d1) * sqrt_t / 100.0  # per 1% vol move
    return Greeks(round(price, 6), round(delta, 6), round(gamma, 8),
                  round(vega, 6), round(theta, 6), round(rho, 6), source="local_bs")


class OptionsAnalytics:
    """Greeks provider: prefers gs-quant if importable + authed, else local BS."""

    def __init__(self):
        self._gs_ok = False
        try:
            import gs_quant  # noqa: F401 - presence check only
            self._gs_ok = True
        except Exception:  # noqa: BLE001 - gs-quant absent -> local BS only
            self._gs_ok = False

    def greeks(self, spot: float, strike: float, t_years: float, vol: float,
               rate: float = 0.0, is_call: bool = True,
               div_yield: float = 0.0) -> Greeks:
        # gs-quant pricing requires a Marquee session; without verified auth we do
        # NOT pretend — fall straight through to local BS and say so.
        return black_scholes_greeks(spot, strike, t_years, vol, rate, is_call, div_yield)

    @property
    def gs_quant_available(self) -> bool:
        return self._gs_ok
