"""Tournament API: run (background), latest, runs list."""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import backend.web.app as webapp
    monkeypatch.setattr(webapp, "TOURNAMENT_STORE", tmp_path)

    from backend.backtest.tournament import StrategyReport, TournamentRun, rank_reports

    def fake_run_tournament(config, runners=None, progress=None):
        rep = StrategyReport(name="fake", kind="trades",
                             metrics={"oos_sharpe": 1.0, "max_drawdown_pct": 5.0,
                                      "profit_factor": 2.0, "n_trades": 150,
                                      "significant": True, "total_return_pct": 12.0})
        run = TournamentRun(started_at="2026-06-11T10:00:00", config_hash="abc")
        run.reports = [rep]
        run.ranked = rank_reports([rep])
        return run

    monkeypatch.setattr(webapp, "run_tournament", fake_run_tournament)
    return TestClient(webapp.app)


def test_latest_empty_404(client):
    assert client.get("/api/tournament/latest").status_code == 404


def test_run_then_latest_and_list(client):
    r = client.post("/api/tournament/run")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    latest = client.get("/api/tournament/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["reports"][0]["name"] == "fake"
    assert body["reports"][0]["gates"]["passed"] is True
    runs = client.get("/api/tournament/runs").json()
    assert len(runs["runs"]) == 1
