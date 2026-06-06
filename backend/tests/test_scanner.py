"""Scanner + scoring + universe tests — pure, no network."""
import numpy as np
import pandas as pd

from backend.scanner.scanner import Scanner
from backend.scanner.score import score_symbol
from backend.universe import load_universe


def _df(closes):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    c = np.array(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c * 1.001, "low": c * 0.999,
                         "close": c, "volume": np.full(n, 1000.0)}, index=idx)


def _uptrend(n=80):
    return _df([100 + i * 0.4 for i in range(n)])


def _downtrend(n=80):
    return _df([100 - i * 0.4 for i in range(n)])


def _flat(n=80):
    return _df([100 + (0.2 if i % 2 else -0.2) for i in range(n)])


def test_score_insufficient_data():
    r = score_symbol("X", _df([100, 101, 102]))
    assert r.error and r.score == 0.0


def test_uptrend_scores_higher_than_downtrend_and_flat():
    up = score_symbol("UP", _uptrend()).score
    down = score_symbol("DN", _downtrend()).score
    flat = score_symbol("FL", _flat()).score
    assert up > flat > down
    assert 0 <= down and up <= 100


def test_uptrend_regime_and_components():
    r = score_symbol("UP", _uptrend())
    assert r.regime == "up" and r.side == "buy"
    assert set(r.components) == {"trend", "momentum", "rsi_room", "regime"}
    assert r.momentum_pct > 0


class _FakeProvider:
    def __init__(self, frames):
        self._frames = frames

    def get_recent_bars_multi(self, symbols, timeframe, lookback, batch=150):
        return {s: self._frames[s] for s in symbols if s in self._frames}


def test_scanner_ranks_and_limits_top_n():
    frames = {"UP": _uptrend(), "DN": _downtrend(), "FLAT": _flat()}
    res = Scanner(_FakeProvider(frames)).scan(["UP", "DN", "FLAT"], top_n=2)
    assert res.scanned == 3
    syms = [c["symbol"] for c in res.candidates]
    assert syms[0] == "UP" and len(syms) == 2   # ranked desc, capped at top_n


def test_scanner_skips_missing_symbols():
    res = Scanner(_FakeProvider({"UP": _uptrend()})).scan(["UP", "MISSING"], top_n=10)
    assert res.scanned == 2 and res.skipped == 1
    assert [c["symbol"] for c in res.candidates] == ["UP"]


def test_scanner_empty_universe():
    assert Scanner(_FakeProvider({})).scan([]).error == "empty universe"


# --- universe loader ---
def test_universe_m7_uses_config_list():
    assert load_universe({"universe": ["AAPL", "MSFT"], "universe_mode": "m7"}) == ["AAPL", "MSFT"]


def test_universe_sp500_loads_snapshot():
    sp = load_universe({"universe_mode": "sp500"})
    assert len(sp) > 400 and "AAPL" in sp        # bundled snapshot present


def test_universe_combined_unions_and_dedups():
    comb = load_universe({"universe_mode": "sp500_nasdaq100"})
    sp = load_universe({"universe_mode": "sp500"})
    assert len(comb) >= len(sp)                  # NASDAQ-100 adds a few non-S&P names
    assert len(comb) == len(set(comb))           # de-duplicated


def test_universe_unknown_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        load_universe({"universe_mode": "nope"})


def test_universe_extra_appended():
    out = load_universe({"universe": ["AAPL"], "universe_mode": "m7",
                         "universe_extra": ["BTC-USD"]})
    assert "BTC-USD" in out and "AAPL" in out
