import os

import pytest
from fastapi.testclient import TestClient

from backend.profiles import (
    apply_active_profile,
    deep_merge,
    resolve_active_profile,
    set_active_profile,
)


@pytest.fixture(autouse=True)
def _reset_profile_override():
    set_active_profile(None)
    yield
    set_active_profile(None)


def _base_config():
    return {
        "universe": ["AAPL"],
        "risk": {"enabled": False, "max_position_pct": 20},
        "research": {"enabled": False, "committee": {"enabled": False}},
        "execution": {"realistic_fills": False},
        "brokers": {"crypto": {"sandbox": True}},
        "profiles": {
            "test": {
                "mode": "test",
                "broker": "mock",
                "universe": ["MSFT"],
                "risk": {"max_position_pct": 5},
                "features": {"research": True, "committee": False},
            },
            "live": {
                "mode": "live",
                "broker": "alpaca_live",
                "risk": {"enabled": True, "max_position_pct": 10},
                "features": {"realistic_fills": True},
            },
        },
    }


def test_profile_loading_from_config_default_test(monkeypatch):
    monkeypatch.delenv("PROFILE", raising=False)
    set_active_profile(None)
    cfg = apply_active_profile(_base_config())
    assert cfg["active_profile"] == "test"
    assert cfg["profile"]["mode"] == "test"
    assert cfg["profile"]["broker"] == "mock"
    assert cfg["universe"] == ["MSFT"]
    assert cfg["research"]["enabled"] is True


def test_active_profile_resolution_env_config_default(monkeypatch):
    set_active_profile(None)
    raw = _base_config()
    assert resolve_active_profile(raw, env={}) == "test"
    raw["active_profile"] = "live"
    assert resolve_active_profile(raw, env={}) == "live"
    assert resolve_active_profile(raw, env={"PROFILE": "test"}) == "test"


def test_deep_merge_profile_values_override_base():
    out = deep_merge(
        {"risk": {"enabled": False, "max_position_pct": 20}, "universe": ["AAPL"]},
        {"risk": {"max_position_pct": 5}},
    )
    assert out["risk"]["enabled"] is False
    assert out["risk"]["max_position_pct"] == 5
    assert out["universe"] == ["AAPL"]


def test_validation_errors_unknown_broker_and_mode():
    raw = _base_config()
    raw["profiles"]["bad_broker"] = {"mode": "test", "broker": "not-real"}
    raw["active_profile"] = "bad_broker"
    with pytest.raises(ValueError, match="Unknown broker"):
        apply_active_profile(raw)

    raw = _base_config()
    raw["profiles"]["bad_mode"] = {"mode": "prod", "broker": "mock"}
    raw["active_profile"] = "bad_mode"
    with pytest.raises(ValueError, match="Unknown mode"):
        apply_active_profile(raw)


def test_profiles_endpoint_shape_and_no_secrets(monkeypatch):
    monkeypatch.setenv("ALPACA_SECRET_KEY", "VERY_SECRET_VALUE")
    from backend.web.app import app

    client = TestClient(app)
    response = client.get("/api/profiles")
    assert response.status_code == 200
    body = response.json()
    assert "profiles" in body
    assert "active" in body
    assert "active_features" in body
    assert {p["name"] for p in body["profiles"]} >= {"test", "live"}
    assert "VERY_SECRET_VALUE" not in response.text


def test_profiles_activate_switches_profile_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    from backend.web.app import app

    client = TestClient(app)
    response = client.post("/api/profiles/activate", json={"name": "live"})
    assert response.status_code == 200
    assert response.json()["active"] == "live"
    assert os.environ.get("LIVE_TRADING") is None

    bad = client.post("/api/profiles/activate", json={"name": "missing"})
    assert bad.status_code == 400

    response = client.post("/api/profiles/activate", json={"name": "test"})
    assert response.status_code == 200


def test_setup_status_shape_and_no_secrets_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "OPENAI_SECRET_VALUE")
    from backend.web.app import app

    client = TestClient(app)
    response = client.get("/api/setup/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"optional_deps", "api_keys_set", "llm_providers_reachable"}
    assert isinstance(body["optional_deps"]["openbb"], bool)
    assert isinstance(body["api_keys_set"]["OPENAI_API_KEY"], bool)
    assert isinstance(body["llm_providers_reachable"]["openai"], bool)
    assert "OPENAI_SECRET_VALUE" not in response.text


def test_config_endpoint_is_secret_free_summary(monkeypatch):
    monkeypatch.setenv("ALPACA_SECRET_KEY", "CONFIG_ENDPOINT_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "CONFIG_OPENAI_SECRET")
    from backend.web.app import app

    client = TestClient(app)
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "runtime",
        "features",
        "universe",
        "universe_mode",
        "scanner",
        "automation",
        "guards",
    }
    assert "profiles" not in body
    assert "research" not in body
    assert "CONFIG_ENDPOINT_SECRET" not in response.text
    assert "CONFIG_OPENAI_SECRET" not in response.text


def test_perspective_page_route_loads():
    from backend.web.app import app

    client = TestClient(app)
    response = client.get("/perspective")
    assert response.status_code == 200
    assert "Perspective" in response.text


def test_live_profile_does_not_enable_live_trading(monkeypatch):
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    raw = _base_config()
    cfg = apply_active_profile(raw, env={"PROFILE": "live"})
    assert cfg["active_profile"] == "live"
    assert cfg["risk"]["enabled"] is True
    assert os.environ.get("LIVE_TRADING") is None
