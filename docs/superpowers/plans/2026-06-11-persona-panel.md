# Persona Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FinceptTerminal-inspired (clean-room) investor-persona panel: 5 fundamentals-driven analyst personas with a per-symbol consensus, served at `GET /api/panel/{symbol}`, rendered on the research page, optionally feeding the committee as one analyst.

**Architecture:** Reuse the existing `Persona` base (`backend/research/personas/base.py`) — only system prompts differ. New `FundamentalsProvider` (yfinance, JSON-cached, injectable fetch) supplies metrics; `PersonaPanel` builds one context string (fundamentals + price summary from `daily_cache` + headlines), runs 5 personas through the existing LLM client (cost caps apply), computes a pure-function consensus, and caches results per symbol under `backend/store/panel_cache/`. The committee gains an optional `extra_reports` seam; app.py wires a panel-consensus report into it when `persona_panel.committee_hook: true` (default false).

**Tech Stack:** Python 3.9 venv (`from __future__ import annotations` in every new file), FastAPI, yfinance (already core), existing ClaudeClient/llm_factory; Next.js + shadcn/ui frontend.

**Spec:** `docs/superpowers/specs/2026-06-11-persona-panel-design.md`

**Conventions:**
- Commands run from repo root; tests ALWAYS via `.venv/bin/python -m pytest backend/tests/... -q` (system python lacks deps).
- LICENSE note: FinceptTerminal is AGPL/commercial — concept only, no code copied. Persona names are generic philosophy labels.

---

### Task 1: Fundamentals provider

**Files:**
- Create: `backend/data/fundamentals.py`
- Test: `backend/tests/test_fundamentals.py`

- [ ] **Step 1: Write the failing test**

```python
"""FundamentalsProvider: cached metric subset; typed failure; field tolerance."""
from __future__ import annotations

import json
import time

import pytest

from backend.data.fundamentals import (
    FundamentalsProvider, FundamentalsUnavailable, METRIC_KEYS,
)


def _info(**overrides):
    base = {
        "trailingPE": 28.5, "forwardPE": 25.1, "pegRatio": 1.8,
        "priceToBook": 12.0, "returnOnEquity": 0.45, "profitMargins": 0.24,
        "operatingMargins": 0.30, "debtToEquity": 140.0,
        "freeCashflow": 9.9e10, "revenueGrowth": 0.08, "earningsGrowth": 0.10,
        "marketCap": 3.1e12, "dividendYield": 0.005, "beta": 1.2,
        "fiftyTwoWeekHigh": 240.0, "fiftyTwoWeekLow": 160.0,
        "irrelevantField": "ignored",
    }
    base.update(overrides)
    return base


def test_get_fetches_once_caches_and_subsets(tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return _info()

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch)
    f1 = p.get("AAPL")
    f2 = p.get("AAPL")
    assert calls == ["AAPL"]                      # second call from cache
    assert f1 == f2
    assert set(f1) <= set(METRIC_KEYS)            # only whitelisted metrics
    assert "irrelevantField" not in f1
    assert f1["trailingPE"] == 28.5


def test_missing_fields_tolerated(tmp_path):
    p = FundamentalsProvider(tmp_path, fetch_fn=lambda s: {"trailingPE": 10.0})
    f = p.get("MSFT")
    assert f == {"trailingPE": 10.0}              # no crash, no padding


def test_ttl_expiry_refetches(tmp_path):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return _info()

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch, ttl_hours=24)
    p.get("NVDA")
    # age the cache file beyond the TTL
    f = p._path("NVDA")
    data = json.loads(f.read_text())
    data["fetched_at"] = time.time() - 25 * 3600
    f.write_text(json.dumps(data))
    p.get("NVDA")
    assert calls == ["NVDA", "NVDA"]


def test_fetch_failure_raises_unavailable(tmp_path):
    def fetch(symbol):
        raise RuntimeError("rate limited")

    p = FundamentalsProvider(tmp_path, fetch_fn=fetch)
    with pytest.raises(FundamentalsUnavailable):
        p.get("TSLA")
```

- [ ] **Step 2: Run to verify FAIL**

Run: `.venv/bin/python -m pytest backend/tests/test_fundamentals.py -q`
Expected: FAIL with `ModuleNotFoundError: backend.data.fundamentals`.

- [ ] **Step 3: Implement `backend/data/fundamentals.py`**

```python
"""Fundamentals provider — compact metric subset for the persona panel.

yfinance Ticker.info backed, JSON-cached per symbol with a TTL. Fetch is
pluggable (tests inject fakes; no network in tests). On fetch failure raises
FundamentalsUnavailable so callers degrade explicitly (spec: personas vote
low-confidence pass) instead of judging on partial data.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional

FetchFn = Callable[[str], dict]

# Whitelist (spec: <=15 metrics + 52w range). Anything else is dropped.
METRIC_KEYS = [
    "trailingPE", "forwardPE", "pegRatio", "priceToBook", "returnOnEquity",
    "profitMargins", "operatingMargins", "debtToEquity", "freeCashflow",
    "revenueGrowth", "earningsGrowth", "marketCap", "dividendYield", "beta",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
]


class FundamentalsUnavailable(RuntimeError):
    pass


def _fetch_yfinance(symbol: str) -> dict:
    import yfinance as yf

    info = yf.Ticker(symbol).info
    if not info:
        return {}
    return dict(info)


class FundamentalsProvider:
    def __init__(self, cache_dir: Path | str, fetch_fn: Optional[FetchFn] = None,
                 *, ttl_hours: float = 24.0):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.fetch_fn = fetch_fn or _fetch_yfinance
        self.ttl_seconds = ttl_hours * 3600.0

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}_fundamentals.json"

    def get(self, symbol: str) -> dict:
        """Whitelisted metrics for one symbol; cached for ttl_hours."""
        p = self._path(symbol)
        if p.exists():
            try:
                data = json.loads(p.read_text())
                if time.time() - float(data.get("fetched_at", 0)) < self.ttl_seconds:
                    return data["metrics"]
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # corrupt cache -> refetch
        try:
            raw = self.fetch_fn(symbol)
        except Exception as exc:  # noqa: BLE001 — converted to a typed failure
            raise FundamentalsUnavailable(f"{symbol}: {exc}") from exc
        metrics = {k: raw[k] for k in METRIC_KEYS if raw.get(k) is not None}
        p.write_text(json.dumps({"fetched_at": time.time(), "metrics": metrics}))
        return metrics
```

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest backend/tests/test_fundamentals.py backend/tests/ -q` → all green.

- [ ] **Step 5: Commit**

```bash
git add backend/data/fundamentals.py backend/tests/test_fundamentals.py
git commit -m "feat(data): cached fundamentals provider for persona panel"
```

---

### Task 2: Legend personas

**Files:**
- Create: `backend/research/personas/legends.py`
- Test: `backend/tests/test_legends.py`

- [ ] **Step 1: Write the failing test**

```python
"""Legend personas: 5 distinct lenses on the shared Persona base."""
from __future__ import annotations

from backend.research.personas.legends import LEGEND_NAMES, build_legend_personas


class FakeClient:
    """Records the system prompt of each structured call; returns a fixed vote."""

    def __init__(self):
        self.systems = []

    def structured(self, *, system, user, tool_name, tool_schema, max_tokens,
                   deep=False, use_case="fast"):
        self.systems.append(system)
        return {"side": "pass", "confidence": 0.2, "rationale": "fake"}


def test_factory_builds_five_distinct_personas():
    client = FakeClient()
    personas = build_legend_personas(client)
    names = [p.name for p in personas]
    assert names == LEGEND_NAMES
    assert len(set(names)) == 5


def test_every_prompt_handles_missing_fundamentals_and_disclaims():
    client = FakeClient()
    for p in build_legend_personas(client):
        p.analyze("AAPL", "fundamentals: unavailable")
    assert len(client.systems) == 5
    for system in client.systems:
        assert "unavailable" in system          # pass-on-missing-data rule
        assert "Not investment advice" in system


def test_votes_flow_through_persona_base():
    client = FakeClient()
    vote = build_legend_personas(client)[0].analyze("AAPL", "ctx")
    assert vote.side == "pass" and vote.confidence == 0.2
```

- [ ] **Step 2: Run to verify FAIL** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/research/personas/legends.py`**

```python
"""Investor-legend personas — fundamentals-driven, long-horizon lenses.

Clean-room implementation inspired by FinceptTerminal's persona concept (its
AGPL code was never read or copied). Generic philosophy labels, no investor
brand names. All reuse the shared Persona base: same vote schema, only the
system prompt differs.
"""
from __future__ import annotations

from .base import Persona

_COMMON = (
    " If the context says fundamentals are unavailable, vote pass with "
    "confidence <= 0.2 — never produce a confident verdict from partial data. "
    "Not investment advice."
)


class ValueMoatPersona(Persona):
    name = "value_moat"
    system = (
        "You are a long-horizon quality-value investor. You look for a durable "
        "competitive moat: return on equity >= 15%, low debt-to-equity, strong "
        "free cash flow, stable margins. You ignore short-term charts entirely. "
        "If the business is great but the valuation is rich, you vote pass."
        + _COMMON
    )


class DeepValuePersona(Persona):
    name = "deep_value"
    system = (
        "You are a margin-of-safety deep-value investor. You want a low "
        "price-to-book and low P/E backed by a strong balance sheet. Use the "
        "debt metrics to reject value traps: cheap with crushing leverage is a "
        "pass, not a long." + _COMMON
    )


class GrowthGarpPersona(Persona):
    name = "growth_garp"
    system = (
        "You are a growth-at-a-reasonable-price investor. You want PEG below "
        "1.5, healthy revenue and earnings growth, and an understandable "
        "business. You are skeptical of hype: growth without profitability "
        "or at an extreme multiple is a pass." + _COMMON
    )


class MacroTopDownPersona(Persona):
    name = "macro_top_down"
    system = (
        "You are a top-down macro strategist. Judge the symbol's sector and "
        "rate sensitivity (use beta and the headlines for macro signals): does "
        "the macro backdrop favor or punish this name over months? Without a "
        "clear macro edge, vote pass." + _COMMON
    )


class RiskChiefPersona(Persona):
    name = "risk_chief"
    system = (
        "You are the panel's chief risk officer. Your job is to argue AGAINST "
        "the strongest apparent thesis: stretched valuation, drawdown from the "
        "52-week high, leverage, concentration or narrative risk. You are the "
        "panel member most willing to vote pass." + _COMMON
    )


LEGEND_NAMES = ["value_moat", "deep_value", "growth_garp",
                "macro_top_down", "risk_chief"]


def build_legend_personas(client) -> list:
    return [ValueMoatPersona(client), DeepValuePersona(client),
            GrowthGarpPersona(client), MacroTopDownPersona(client),
            RiskChiefPersona(client)]
```

- [ ] **Step 4: Run tests** — new file + full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/research/personas/legends.py backend/tests/test_legends.py
git commit -m "feat(research): five legend personas (clean-room, generic labels)"
```

---

### Task 3: Panel orchestrator + consensus

**Files:**
- Create: `backend/research/panel.py`
- Test: `backend/tests/test_panel.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to verify FAIL** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `backend/research/panel.py`**

```python
"""Persona panel — orchestrates the legend personas into one cached verdict.

Pure pieces (consensus, build_context, price_summary) are separated from the
I/O orchestrator (PersonaPanel) so the math is exhaustively testable. The
panel NEVER fails because fundamentals are missing — it degrades the context
and lets the personas vote pass (spec: Error handling).
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from backend.data.fundamentals import FundamentalsUnavailable
from .base import PersonaVote
from .personas.legends import build_legend_personas

VERDICT_THRESHOLD = 0.15
_DIR = {"long": 1.0, "short": -1.0, "pass": 0.0}


@dataclass
class PanelResult:
    symbol: str
    verdict: str
    score: float
    votes: list = field(default_factory=list)      # list[PersonaVote]
    fundamentals_available: bool = True
    generated_at: str = ""
    cached: bool = False


def consensus(votes: list, weights: Optional[dict] = None) -> "tuple[str, float]":
    """Weighted directional score in [-1, 1] -> verdict via +/-0.15 threshold."""
    weights = weights or {}
    total_w = sum(weights.get(v.name, 1.0) for v in votes)
    if total_w <= 0 or not votes:
        return "pass", 0.0
    score = sum(weights.get(v.name, 1.0) * _DIR[v.side] * v.confidence
                for v in votes) / total_w
    if score >= VERDICT_THRESHOLD:
        return "long", round(score, 4)
    if score <= -VERDICT_THRESHOLD:
        return "short", round(score, 4)
    return "pass", round(score, 4)


def price_summary(df: Optional[pd.DataFrame]) -> Optional[dict]:
    """1y return / annualized vol / distance from 52w extremes, from daily bars."""
    if df is None or len(df) < 60:
        return None
    close = df["close"].iloc[-252:]
    rets = close.pct_change().dropna()
    last = float(close.iloc[-1])
    hi, lo = float(close.max()), float(close.min())
    return {
        "return_1y_pct": round((last / float(close.iloc[0]) - 1.0) * 100.0, 2),
        "vol_ann_pct": round(float(rets.std()) * (252 ** 0.5) * 100.0, 2),
        "off_52w_high_pct": round((last / hi - 1.0) * 100.0, 2),
        "off_52w_low_pct": round((last / lo - 1.0) * 100.0, 2),
    }


def build_context(fundamentals: Optional[dict], price: Optional[dict],
                  headlines: list) -> "tuple[str, bool]":
    """One compact context string for every persona. Returns (text, available)."""
    lines = []
    available = bool(fundamentals)
    if fundamentals:
        lines.append("Fundamentals: " + "; ".join(
            f"{k}: {v}" for k, v in fundamentals.items()))
    else:
        lines.append("fundamentals: unavailable")
    if price:
        lines.append("Price (1y): " + "; ".join(
            f"{k}: {v}" for k, v in price.items()))
    else:
        lines.append("price summary: unavailable")
    if headlines:
        lines.append("Recent headlines: " + " | ".join(headlines[:5]))
    return "\n".join(lines), available


class PersonaPanel:
    def __init__(self, client, fundamentals_provider, *, cache_dir: Path | str,
                 daily_bars_fn: Callable[[str], Optional[pd.DataFrame]],
                 headlines_fn: Callable[[str], list],
                 ttl_hours: float = 24.0, weights: Optional[dict] = None):
        self._client = client
        self._fund = fundamentals_provider
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._daily_bars_fn = daily_bars_fn
        self._headlines_fn = headlines_fn
        self.ttl_seconds = ttl_hours * 3600.0
        self.weights = weights or {}

    def _path(self, symbol: str) -> Path:
        safe = symbol.upper().replace("/", "_").replace("..", "__")
        return self.dir / f"{safe}_panel.json"

    def run(self, symbol: str, *, refresh: bool = False) -> PanelResult:
        p = self._path(symbol)
        if not refresh and p.exists():
            try:
                data = json.loads(p.read_text())
                if time.time() - float(data.get("saved_at", 0)) < self.ttl_seconds:
                    res = PanelResult(**data["result"])
                    res.votes = [PersonaVote(**v) for v in res.votes]
                    res.cached = True
                    return res
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass  # corrupt cache -> recompute

        try:
            fundamentals = self._fund.get(symbol)
        except FundamentalsUnavailable:
            fundamentals = None
        try:
            price = price_summary(self._daily_bars_fn(symbol))
        except Exception:  # noqa: BLE001 — price summary is best-effort
            price = None
        try:
            headlines = self._headlines_fn(symbol) or []
        except Exception:  # noqa: BLE001 — headlines are best-effort
            headlines = []

        context, available = build_context(fundamentals, price, headlines)
        votes = [persona.analyze(symbol, context)
                 for persona in build_legend_personas(self._client)]
        verdict, score = consensus(votes, self.weights)
        result = PanelResult(
            symbol=symbol.upper(), verdict=verdict, score=score, votes=votes,
            fundamentals_available=available,
            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"), cached=False,
        )
        payload = asdict(result)
        p.write_text(json.dumps({"saved_at": time.time(), "result": payload}))
        return result
```

- [ ] **Step 4: Run tests** — new file + full suite green.

- [ ] **Step 5: Commit**

```bash
git add backend/research/panel.py backend/tests/test_panel.py
git commit -m "feat(research): persona panel orchestrator with cached consensus"
```

---

### Task 4: `/api/panel/{symbol}` endpoint + config block

**Files:**
- Modify: `backend/web/app.py`
- Modify: `backend/config.yaml`
- Test: `backend/tests/test_panel_api.py`

- [ ] **Step 1: Write the failing test**

```python
"""Panel API: 503 without LLM; cached result with refresh param."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    import backend.web.app as webapp
    return TestClient(webapp.app), webapp, monkeypatch


def test_panel_503_when_unconfigured(client):
    tc, webapp, monkeypatch = client
    monkeypatch.setattr(webapp, "_panel", None)
    r = tc.get("/api/panel/AAPL")
    assert r.status_code == 503
    assert "llm unavailable" in r.json()["detail"]


def test_panel_returns_result_and_passes_refresh(client):
    tc, webapp, monkeypatch = client

    calls = {}

    class FakePanel:
        def run(self, symbol, *, refresh=False):
            calls["symbol"], calls["refresh"] = symbol, refresh
            from backend.research.panel import PanelResult
            from backend.research.base import PersonaVote
            return PanelResult(symbol=symbol, verdict="long", score=0.4,
                               votes=[PersonaVote("value_moat", "long", 0.8, "ok")],
                               generated_at="t")

    monkeypatch.setattr(webapp, "_panel", FakePanel())
    r = tc.get("/api/panel/aapl?refresh=true")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "long"
    assert body["votes"][0]["name"] == "value_moat"
    assert calls == {"symbol": "AAPL", "refresh": True}
```

- [ ] **Step 2: Run to verify FAIL** — `_panel` attribute missing → AttributeError / 404.

- [ ] **Step 3: Wire in `backend/web/app.py`**

Near the existing `_copilot` wiring block (after it), add:

```python
# Persona panel (FinceptTerminal-inspired, clean-room). Built only when an LLM
# is configured AND persona_panel.enabled (default true). On-demand endpoint —
# never touches the trading path.
_panel = None  # PersonaPanel | None
_pp_cfg = _config.get("persona_panel", {})
if _llm is not None and _pp_cfg.get("enabled", True):
    from ..data.daily_cache import DailyBarCache
    from ..data.fundamentals import FundamentalsProvider
    from ..research.panel import PersonaPanel

    _store_dir = Path(__file__).resolve().parent.parent / "store"
    _panel_daily = DailyBarCache(_store_dir / "daily_cache")

    def _panel_bars(sym: str):
        try:
            return _panel_daily.get(sym)
        except Exception:  # noqa: BLE001 — price summary is best-effort
            return None

    _panel = PersonaPanel(
        _llm,
        FundamentalsProvider(_store_dir / "fundamentals_cache"),
        cache_dir=_store_dir / "panel_cache",
        daily_bars_fn=_panel_bars,
        headlines_fn=lambda sym: [h.headline for h in
                                  _news_unified.latest(symbol=sym, limit=5)],
        ttl_hours=float(_pp_cfg.get("cache_ttl_hours", 24)),
        weights=_pp_cfg.get("weights") or {},
    )
```

(`Path` import: app.py already imports it — verify, otherwise add `from pathlib import Path`.)

After the `/api/copilot/{symbol}` endpoint add:

```python
@app.get("/api/panel/{symbol}")
async def api_panel(symbol: str, refresh: bool = False) -> dict:
    """Investor-persona panel verdict for one symbol (cached, on-demand)."""
    if _panel is None:
        raise HTTPException(status_code=503, detail="llm unavailable")
    import asyncio as _a
    from dataclasses import asdict as _asdict

    res = await _a.to_thread(_panel.run, symbol.upper(), refresh=refresh)
    return _asdict(res)
```

In `backend/config.yaml`, after the `pairs_statarb:` block:

```yaml
# Persona panel (FinceptTerminal-inspired, clean-room). On-demand research
# surface; committee_hook adds ONE persona_panel analyst to the committee.
persona_panel:
  enabled: true
  cache_ttl_hours: 24
  weights: {}              # per-persona weight overrides; default equal
  committee_hook: false
```

- [ ] **Step 4: Run tests** — new file + full suite green (`.venv/bin/python -m pytest backend/tests/ -q`).

- [ ] **Step 5: Commit**

```bash
git add backend/web/app.py backend/config.yaml backend/tests/test_panel_api.py
git commit -m "feat(api): /api/panel/{symbol} persona panel endpoint"
```

---

### Task 5: Committee hook (`extra_reports` seam)

**Files:**
- Modify: `backend/research/agents/committee.py` (add `extra_reports` kwarg)
- Modify: `backend/web/app.py` (committee endpoint builds the panel report when hooked)
- Test: `backend/tests/test_committee_hook.py`

- [ ] **Step 1: Write the failing test**

```python
"""Committee hook: extra_reports seam; panel report mapping."""
from __future__ import annotations

from backend.research.base import AnalystReport
from backend.research.panel import PanelResult
from backend.web.app import _panel_report  # helper added in this task


def test_panel_report_maps_verdict_and_score():
    res = PanelResult(symbol="AAPL", verdict="long", score=0.42, votes=[],
                      fundamentals_available=True, generated_at="t")
    rep = _panel_report(res)
    assert isinstance(rep, AnalystReport)
    assert rep.role == "persona_panel"
    assert rep.side == "long"
    assert rep.confidence == 0.42
    assert rep.available is True


def test_panel_report_pass_maps_to_zero_signed_confidence():
    res = PanelResult(symbol="AAPL", verdict="short", score=-0.3, votes=[],
                      fundamentals_available=False, generated_at="t")
    rep = _panel_report(res)
    assert rep.side == "short"
    assert rep.confidence == 0.3                  # abs(score)
    assert rep.available is True


def test_run_committee_accepts_extra_reports(monkeypatch):
    """extra_reports flow into the analyst digest; default None unchanged."""
    import backend.research.agents.committee as committee_mod
    captured = {}

    def fake_run_analysts(client, symbol, **kw):
        return [AnalystReport(role="value", side="pass", confidence=0.1,
                              rationale="r")]

    def fake_summarize(reports):
        captured["roles"] = [r.role for r in reports]
        raise RuntimeError("stop early — only the analyst stage matters here")

    monkeypatch.setattr(committee_mod, "run_analysts", fake_run_analysts)
    monkeypatch.setattr(committee_mod, "summarize_reports", fake_summarize)

    extra = AnalystReport(role="persona_panel", side="long", confidence=0.4,
                          rationale="panel")
    committee_mod.run_committee(
        object(), "AAPL", "buy", context="c", headlines=[], gate=_gate(),
        bb_meta={}, cfg={}, extra_reports=[extra],
    )
    assert captured["roles"] == ["value", "persona_panel"]


def _gate():
    from backend.research.base import CatalystVerdict
    return CatalystVerdict(verdict="allow")
```

NOTE: read `run_committee`'s error handling first — it wraps stages in try/except
and returns a degraded verdict on exception, so the fake `summarize_reports`
raising is fine (the function returns instead of crashing). If `CatalystVerdict`'s
verdict literal differs (e.g. "allow" vs another enum string), use a valid value
from `backend/research/base.py`.

- [ ] **Step 2: Run to verify FAIL** — `_panel_report` missing; `extra_reports` unexpected kwarg.

- [ ] **Step 3: Implement.** In `backend/research/agents/committee.py`, change the signature and the analyst stage:

```python
def run_committee(
    client: ClaudeClient, symbol: str, side: str, *,
    context: str, headlines: list[str], gate: CatalystVerdict,
    bb_meta: dict, cfg: dict, extra_reports: list | None = None,
) -> CommitteeVerdict:
```

and right after `analysts = run_analysts(...)`:

```python
        if extra_reports:
            analysts = analysts + list(extra_reports)
```

In `backend/web/app.py` add the module-level helper (near the panel wiring):

```python
def _panel_report(res) -> "AnalystReport":
    """Map a PanelResult to ONE committee AnalystReport (spec: committee hook)."""
    from ..research.base import AnalystReport

    return AnalystReport(
        role="persona_panel", side=res.verdict,
        confidence=abs(res.score),
        rationale=f"panel consensus {res.verdict} (score {res.score}); "
                  f"fundamentals {'ok' if res.fundamentals_available else 'unavailable'}",
        available=True,
    )
```

In the `/api/committee/{symbol}` endpoint, where `run_committee` is called, build
the extras first (read the surrounding code and keep its style):

```python
    extra_reports = None
    if _panel is not None and _pp_cfg.get("committee_hook", False):
        try:
            extra_reports = [_panel_report(_panel.run(sym))]
        except Exception:  # noqa: BLE001 — the hook must never break the committee
            extra_reports = None
```

and pass `extra_reports=extra_reports` to `run_committee`.

- [ ] **Step 4: Run tests** — new file + full suite green (existing committee tests must pass unchanged — the kwarg defaults to None).

- [ ] **Step 5: Commit**

```bash
git add backend/research/agents/committee.py backend/web/app.py backend/tests/test_committee_hook.py
git commit -m "feat(research): optional persona-panel analyst in committee (default off)"
```

---

### Task 6: Research-page panel card (frontend)

**Files:**
- Modify: `frontend/lib/types.ts`, `frontend/lib/api.ts`
- Create: `frontend/components/core/persona-panel.tsx`
- Modify: `frontend/app/research/page.tsx`

Read `frontend/components/core/tournament-client.tsx` first and mirror its
conventions (Card/Badge/Button/Table primitives, sonner toasts, fmt helpers).

- [ ] **Step 1: Types** (append to `frontend/lib/types.ts`):

```typescript
export type PanelVote = {
  name: string;
  side: "long" | "short" | "pass";
  confidence: number;
  rationale: string;
};

export type PanelResult = {
  symbol: string;
  verdict: "long" | "short" | "pass";
  score: number;
  votes: PanelVote[];
  fundamentals_available: boolean;
  generated_at: string;
  cached: boolean;
};
```

- [ ] **Step 2: API helper** (append to `frontend/lib/api.ts`, extend type import):

```typescript
export function getPanel(symbol: string, refresh = false) {
  return api<PanelResult>(
    `/api/panel/${encodeURIComponent(symbol)}${refresh ? "?refresh=true" : ""}`,
  );
}
```

- [ ] **Step 3: Component** `frontend/components/core/persona-panel.tsx`:

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { getPanel } from "@/lib/api";
import type { PanelResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const sideColor: Record<string, string> = {
  long: "bg-emerald-500/15 text-emerald-500",
  short: "bg-red-500/15 text-red-500",
  pass: "bg-secondary text-muted-foreground",
};

export function PersonaPanel() {
  const [symbol, setSymbol] = useState("AAPL");
  const [data, setData] = useState<PanelResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async (refresh = false) => {
    setBusy(true);
    try {
      setData(await getPanel(symbol.trim().toUpperCase(), refresh));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "panel failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Persona Panel</CardTitle>
        <CardDescription>
          Five investing philosophies judge one symbol from fundamentals, price
          history, and headlines. Not investment advice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol, e.g. AAPL"
            className="w-40"
            onKeyDown={(e) => e.key === "Enter" && load()}
          />
          <Button onClick={() => load()} disabled={busy || !symbol.trim()}>
            {busy ? "Asking the panel…" : "Run panel"}
          </Button>
          {data && (
            <Button variant="outline" onClick={() => load(true)} disabled={busy}>
              Refresh
            </Button>
          )}
        </div>

        {data && (
          <>
            <div className="flex items-center gap-3">
              <Badge className={cn("text-sm", sideColor[data.verdict])}>
                consensus: {data.verdict} ({data.score >= 0 ? "+" : ""}
                {data.score.toFixed(2)})
              </Badge>
              {!data.fundamentals_available && (
                <span className="text-xs text-amber-600">
                  fundamentals unavailable — low-confidence verdicts
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {data.cached ? "cached" : "fresh"} · {data.generated_at}
              </span>
            </div>
            <ul className="space-y-2">
              {data.votes.map((v) => (
                <li key={v.name} className="flex items-start gap-2 text-sm">
                  <Badge className={cn("shrink-0", sideColor[v.side])}>
                    {v.side} {(v.confidence * 100).toFixed(0)}%
                  </Badge>
                  <span className="font-medium">{v.name}</span>
                  <span className="text-muted-foreground">{v.rationale}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
```

(If `@/components/ui/input` does not exist, check `frontend/components/ui/` for
the closest primitive used elsewhere — e.g. the setup page — and reuse that.)

- [ ] **Step 4: Page** — replace `frontend/app/research/page.tsx` content:

```tsx
import { PersonaPanel } from "@/components/core/persona-panel";
import { PageTitle } from "@/components/shell/page-title";

export default function ResearchPage() {
  return (
    <>
      <PageTitle
        title="Research / News"
        description="Persona panel verdicts, unified headlines, and committee endpoints (/api/panel, /api/news/latest, /api/copilot)."
      />
      <PersonaPanel />
    </>
  );
}
```

- [ ] **Step 5: Build** — `pnpm --dir frontend build` must succeed; `pnpm --dir frontend exec tsc --noEmit` clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/components/core/persona-panel.tsx frontend/app/research/page.tsx
git commit -m "feat(web): persona panel card on the research page"
```

---

### Task 7: Full-suite verification + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** `.venv/bin/python -m pytest backend/tests/ -q` → all green.
- [ ] **Step 2:** `pnpm --dir frontend build` → success.
- [ ] **Step 3:** README "What It Includes": after the strategy-tournament bullet add:

```markdown
- Persona panel: five investor-philosophy AI analysts (value/moat, deep value,
  GARP, macro, risk chief) deliver a cached per-symbol consensus on the
  research page; optionally joins the LLM committee as one analyst.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: persona panel in README"
```
