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
