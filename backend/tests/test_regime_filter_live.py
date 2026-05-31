"""Tests for the (A) regime filter wired into the live runner."""
import pandas as pd

from backend.runner import Engine, regime_allows


# ---- pure regime_allows logic ----
def test_mean_reversion_only_in_range():
    assert regime_allows("spike_fade", "buy", "range") is True
    assert regime_allows("spike_fade", "buy", "up") is False
    assert regime_allows("spike_fade", "sell", "down") is False


def test_trend_following_aligned_only():
    assert regime_allows("ema_momentum", "buy", "up") is True
    assert regime_allows("ema_momentum", "sell", "up") is False     # counter-trend
    assert regime_allows("donchian_breakout", "sell", "down") is True
    assert regime_allows("donchian_breakout", "buy", "down") is False
    assert regime_allows("ema_momentum", "buy", "range") is False   # no trend


def test_unknown_strategy_always_allowed():
    assert regime_allows("some_custom", "buy", "range") is True


# ---- engine honors the filter flag (no network) ----
class _FiringStrat:
    name = "spike_fade"
    def __init__(self, side): self._side = side
    def evaluate(self, ctx):
        from backend.strategy.base import StrategySignal
        return StrategySignal(side=self._side, strength=2.0, meta={"z": 2.0, "rsi": 25})


def _engine(filter_enabled, regime):
    cfg = {"regime": {"ema_period": 50, "slope_threshold": 0.0005,
                      "filter_enabled": filter_enabled},
           "strategies": {"signal": [], "confirmations": []}}
    eng = Engine(cfg, provider=None)
    eng.signal_strategies = [_FiringStrat("buy")]
    eng.confirmation_strategies = []
    # stub regime detection + tape/print so _emit doesn't need real infra
    import backend.runner as R
    eng._emitted = []
    eng._emit = lambda *a, **k: eng._emitted.append(a)
    eng._forced_regime = regime
    # monkeypatch detect to our forced regime by injecting a window the detector reads
    return eng


def test_engine_suppresses_misaligned_when_filter_on(monkeypatch):
    import backend.runner as R
    monkeypatch.setattr(R, "detect_regime", lambda *a, **k: "up")  # trend up
    eng = _engine(filter_enabled=True, regime="up")
    win = pd.DataFrame({"open": [1]*60, "high": [1]*60, "low": [1]*60,
                        "close": [1.0]*60, "volume": [1]*60})
    eng.windows["X"] = win
    eng._evaluate("X", {"close": 1.0})
    assert eng._emitted == []   # spike_fade buy in an up-trend is suppressed


def test_engine_allows_misaligned_when_filter_off(monkeypatch):
    import backend.runner as R
    monkeypatch.setattr(R, "detect_regime", lambda *a, **k: "up")
    eng = _engine(filter_enabled=False, regime="up")
    win = pd.DataFrame({"open": [1]*60, "high": [1]*60, "low": [1]*60,
                        "close": [1.0]*60, "volume": [1]*60})
    eng.windows["X"] = win
    eng._evaluate("X", {"close": 1.0})
    assert len(eng._emitted) == 1   # filter off -> signal passes through
