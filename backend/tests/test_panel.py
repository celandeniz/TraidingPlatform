"""PersonaPanel: consensus math, context building, caching, degradation."""
from __future__ import annotations

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
    def __init__(self, side="long", conf=0.8):
        self.calls = 0
        self.side, self.conf = side, conf

    def structured(self, *, system, user, tool_name, tool_schema, max_tokens,
                   deep=False, use_case="fast"):
        self.calls += 1
        return {"side": self.side, "confidence": self.conf, "rationale": "ok"}


def _panel(tmp_path, client, fundamentals=None):
    class FakeFundamentals:
        def get(self, symbol):
            if fundamentals is None:
                from backend.data.fundamentals import FundamentalsUnavailable
                raise FundamentalsUnavailable(symbol)
            return fundamentals

    return PersonaPanel(client, FakeFundamentals(), cache_dir=tmp_path,
                        daily_bars_fn=lambda s: None,
                        headlines_fn=lambda s: ["h1", "h2"])


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
