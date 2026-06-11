"""PersonaPanel: consensus math, context building, caching, degradation."""
from __future__ import annotations

import json
import time

import pandas as pd

from backend.research.base import PersonaVote
from backend.research.panel import PersonaPanel, build_context, consensus, price_summary


# ---------- consensus (pure) ----------

def _v(name, side, conf):
    return PersonaVote(name=name, side=side, confidence=conf, rationale="r")


def test_consensus_all_long():
    verdict, score = consensus([_v("a", "long", 0.8), _v("b", "long", 0.6)])
    assert verdict == "long" and score > 0.15


def test_consensus_split_is_pass():
    verdict, score = consensus([_v("a", "long", 0.7), _v("b", "short", 0.7)])
    assert verdict == "pass" and abs(score) < 0.15


def test_consensus_weighted():
    verdict, _ = consensus([_v("a", "long", 0.9), _v("b", "short", 0.9)],
                           weights={"a": 3.0, "b": 1.0})
    assert verdict == "long"


def test_consensus_all_pass_zero():
    verdict, score = consensus([_v("a", "pass", 0.9)])
    assert verdict == "pass" and score == 0.0


# ---------- context building (pure) ----------

def test_build_context_includes_metrics_and_headlines():
    ctx, available = build_context(
        {"trailingPE": 28.5, "returnOnEquity": 0.45},
        {"return_1y_pct": 12.3, "vol_ann_pct": 22.0, "off_52w_high_pct": -5.0},
        ["Apple ships new chip", "Margins expand"],
    )
    assert available is True
    assert "trailingPE: 28.5" in ctx and "return_1y_pct" in ctx
    assert "Apple ships new chip" in ctx


def test_build_context_unavailable_fundamentals():
    ctx, available = build_context(None, None, [])
    assert available is False
    assert "fundamentals: unavailable" in ctx


def test_price_summary_from_daily_frame():
    idx = pd.bdate_range("2025-06-11", periods=260, tz="UTC")
    px = pd.Series([100 + i * 0.1 for i in range(260)], index=idx)
    df = pd.DataFrame({"open": px, "high": px * 1.01, "low": px * 0.99,
                       "close": px, "volume": 1e6})
    s = price_summary(df)
    assert s["return_1y_pct"] > 0
    assert s["off_52w_high_pct"] <= 0


# ---------- orchestration ----------

class FakeClient:
    """Simple fake that always returns the same side/conf, or cycles a queue."""

    def __init__(self, side="long", conf=0.8, queue=None):
        """
        queue: optional list of (side, conf) tuples returned in order;
               once exhausted, wraps to last entry.
        """
        self.calls = 0
        self.side, self.conf = side, conf
        self._queue = list(queue) if queue else None

    def structured(self, *, system, user, tool_name, tool_schema, max_tokens,
                   deep=False, use_case="fast"):
        self.calls += 1
        if self._queue:
            idx = min(self.calls - 1, len(self._queue) - 1)
            side, conf = self._queue[idx]
        else:
            side, conf = self.side, self.conf
        return {"side": side, "confidence": conf, "rationale": "ok"}


def _panel(tmp_path, client, fundamentals=None, weights=None):
    class FakeFundamentals:
        def get(self, symbol):
            if fundamentals is None:
                from backend.data.fundamentals import FundamentalsUnavailable
                raise FundamentalsUnavailable(symbol)
            return fundamentals

    return PersonaPanel(client, FakeFundamentals(), cache_dir=tmp_path,
                        daily_bars_fn=lambda s: None,
                        headlines_fn=lambda s: ["h1", "h2"],
                        weights=weights or {})


def test_panel_runs_five_personas_and_caches(tmp_path):
    client = FakeClient()
    panel = _panel(tmp_path, client, fundamentals={"trailingPE": 10.0})
    r1 = panel.run("AAPL")
    assert client.calls == 5
    assert r1.verdict == "long" and len(r1.votes) == 5
    assert r1.fundamentals_available is True and r1.cached is False
    r2 = panel.run("AAPL")
    assert client.calls == 5                      # served from cache
    assert r2.cached is True


def test_panel_refresh_bypasses_cache(tmp_path):
    client = FakeClient()
    panel = _panel(tmp_path, client, fundamentals={"trailingPE": 10.0})
    panel.run("AAPL")
    panel.run("AAPL", refresh=True)
    assert client.calls == 10


def test_panel_degrades_without_fundamentals(tmp_path):
    client = FakeClient(side="pass", conf=0.1)
    panel = _panel(tmp_path, client, fundamentals=None)
    r = panel.run("MSFT")
    assert r.fundamentals_available is False
    assert r.verdict == "pass"


# ---------- price_summary zero-price guard ----------

def test_price_summary_all_zeros_returns_none():
    """Frame with all closes 0.0 must return None (no ZeroDivisionError)."""
    idx = pd.bdate_range("2024-01-01", periods=100, tz="UTC")
    df = pd.DataFrame({"open": 0.0, "high": 0.0, "low": 0.0,
                       "close": 0.0, "volume": 0.0}, index=idx)
    assert price_summary(df) is None


def test_price_summary_zero_first_close_returns_none():
    """Frame where only the first close in the 252-window is 0.0 must return None."""
    idx = pd.bdate_range("2024-01-01", periods=100, tz="UTC")
    closes = [100.0] * 100
    closes[0] = 0.0            # first value is 0 → 1y-return denominator is 0
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                       "close": closes, "volume": 1e6}, index=idx)
    assert price_summary(df) is None


# ---------- consensus negative-weight clamp ----------

def test_consensus_negative_weight_clamped_to_zero():
    """Negative weight must be clamped to 0, never flip the vote direction."""
    # "a" votes long with high confidence; "b" votes long too.
    # weight of "a" is -3.0 → clamped to 0 → only "b" (weight 1.0) counts.
    # Result: still "long" (not flipped to short).
    verdict, score = consensus(
        [_v("a", "long", 0.9), _v("b", "long", 0.9)],
        weights={"a": -3.0, "b": 1.0},
    )
    assert verdict == "long", f"Expected 'long' but got '{verdict}' (score={score})"
    assert score > 0


# ---------- corrupt cache test ----------

def test_panel_corrupt_cache_recomputes(tmp_path):
    """Garbage cache JSON must be ignored and a fresh compute performed."""
    client = FakeClient()
    panel = _panel(tmp_path, client, fundamentals={"trailingPE": 15.0})
    # Write garbage to the cache file before any run
    panel._path("AAPL").write_text("{not json")
    r = panel.run("AAPL")
    assert client.calls == 5                 # recomputed — 5 persona calls
    assert r.verdict == "long"
    assert r.cached is False


# ---------- constructor weights wiring ----------

def test_panel_constructor_weights_wiring(tmp_path):
    """weights= kwarg must reach consensus and influence the verdict.

    Strategy: FakeClient returns long(0.9) on the FIRST call (value_moat),
    and short(0.9) on all subsequent calls.  We zero out every persona except
    value_moat (first).

    With correct wiring:  only value_moat (long 0.9, weight 1.0) counts
                          → verdict "long".
    With broken wiring (equal weights): 1 long vs 4 short → verdict "short".
    """
    queue = [("long", 0.9)] + [("short", 0.9)] * 4
    client = FakeClient(queue=queue)
    weights = {
        "value_moat":    1.0,
        "deep_value":    0.0,
        "growth_garp":   0.0,
        "macro_top_down": 0.0,
        "risk_chief":    0.0,
    }
    panel = _panel(tmp_path, client,
                   fundamentals={"trailingPE": 15.0},
                   weights=weights)
    r = panel.run("AAPL")
    assert r.verdict == "long", (
        f"Expected 'long' (value_moat dominates) but got '{r.verdict}'. "
        "Weights are likely not wired into consensus."
    )


# ---------- TTL expiry test ----------

def test_panel_ttl_expiry_recomputes(tmp_path):
    """After the TTL elapses the panel must recompute, not serve stale cache."""
    client = FakeClient()
    panel = _panel(tmp_path, client, fundamentals={"trailingPE": 15.0})
    panel.run("AAPL")
    assert client.calls == 5

    # Backdate saved_at by 25 hours (TTL is 24 h)
    cache_path = panel._path("AAPL")
    data = json.loads(cache_path.read_text())
    data["saved_at"] = time.time() - 25 * 3600
    cache_path.write_text(json.dumps(data))

    panel.run("AAPL")
    assert client.calls == 10   # recomputed
