from backend.research.base import CatalystVerdict, FundamentalScore
from backend.research.decision_layer import decide


def _gate(v):
    return CatalystVerdict(verdict=v, reasons=[v])


def test_suppress_forces_none():
    d = decide("TSLA", "buy", tier="high_vol", regime="range", gate=_gate("SUPPRESS"))
    assert d.action == "NONE"
    assert "catalyst" in d.rationale


def test_with_trend_only_blocks_counter_trend_fade():
    # buy fade in a down regime is counter-trend -> blocked
    d = decide("TSLA", "buy", tier="high_vol", regime="down", gate=_gate("WITH_TREND_ONLY"))
    assert d.action == "NONE"


def test_with_trend_only_allows_aligned():
    d = decide("TSLA", "buy", tier="high_vol", regime="up", gate=_gate("WITH_TREND_ONLY"))
    assert d.action == "CALL"


def test_allow_high_vol_buy_is_call():
    d = decide("NVDA", "buy", tier="high_vol", regime="range", gate=_gate("ALLOW"))
    assert d.action == "CALL"
    assert d.side == "buy"


def test_allow_core_sell_is_none():
    d = decide("AAPL", "sell", tier="core", regime="range", gate=_gate("ALLOW"))
    assert d.action == "NONE"  # no spot short in v1


def test_fundamental_veto_when_enabled():
    f = FundamentalScore(score=-0.8, label="weak", rationale="x", available=True)
    d = decide("AAPL", "buy", tier="core", regime="range", gate=_gate("ALLOW"),
               fundamental=f, fundamental_can_veto=True)
    assert d.action == "NONE"
    assert "veto" in d.rationale
