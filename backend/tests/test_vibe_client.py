"""Vibe-Trading client/config/factory tests — no network.

A fake `requests` module is injected into sys.modules so the client's lazy
`import requests` picks it up. Verifies: config parsing, health up/down,
factory gating, defensive request dicts, and SSE parsing.
"""
import sys
import types

import pytest

from backend.integrations.vibe_trading import (
    VibeClient, VibeConfig, build_vibe_client,
)


class _Settings:
    vibe_api_auth_key = ""


def _cfg(**over):
    base = {
        "vibe_trading": {
            "enabled": True,
            "base_url": "http://vibe:8899",
            "health_path": "/health",
            "request_timeout": 5,
            "health_timeout": 1,
            "purposes": {"research": True, "strategy": True, "execution": False},
        }
    }
    base["vibe_trading"].update(over)
    return base


class _Resp:
    def __init__(self, *, status=200, json_data=None, text="", lines=None, raise_exc=None):
        self.status_code = status
        self._json = json_data
        self.text = text
        self._lines = lines or []
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_requests(handler):
    """Build a fake `requests` module whose get/request/post call `handler`."""
    mod = types.ModuleType("requests")

    def _call(method, url, **kw):
        return handler(method, url, kw)

    mod.get = lambda url, **kw: _call("GET", url, **kw)
    mod.post = lambda url, **kw: _call("POST", url, **kw)
    mod.request = lambda method, url, **kw: _call(method, url, **kw)
    return mod


@pytest.fixture
def inject_requests(monkeypatch):
    def _install(handler):
        monkeypatch.setitem(sys.modules, "requests", _fake_requests(handler))
    return _install


# --- config ---------------------------------------------------------------
def test_config_parsing_and_helpers():
    c = VibeConfig.from_config(_Settings(), _cfg())
    assert c.enabled and c.base_url == "http://vibe:8899"
    assert c.url("/x") == "http://vibe:8899/x"
    assert c.purpose_enabled("research") and not c.purpose_enabled("execution")
    assert c.headers() == {}


def test_config_auth_header():
    class S:
        vibe_api_auth_key = "tok"
    c = VibeConfig.from_config(S(), _cfg())
    assert c.headers() == {"Authorization": "Bearer tok"}


# --- health ---------------------------------------------------------------
def test_health_ok(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(status=200))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    assert client.health()["ok"] is True


def test_health_down(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(raise_exc=ConnectionError("refused")))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    out = client.health()
    assert out["ok"] is False and "refused" in out["detail"]


# --- factory gating -------------------------------------------------------
def test_factory_disabled_returns_none():
    assert build_vibe_client(_Settings(), _cfg(enabled=False)) is None


def test_factory_unreachable_returns_none(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(raise_exc=ConnectionError("refused")))
    assert build_vibe_client(_Settings(), _cfg()) is None


def test_factory_healthy_returns_client(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(status=200))
    client = build_vibe_client(_Settings(), _cfg())
    assert isinstance(client, VibeClient)


# --- request helpers ------------------------------------------------------
def test_get_json_wraps_plain_payload(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(json_data={"value": 1}))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    assert client.get_json("/x") == {"ok": True, "data": {"value": 1}}


def test_post_json_passes_through_ok_flag(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(json_data={"ok": True, "x": 2}))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    assert client.post_json("/x", {"a": 1}) == {"ok": True, "x": 2}


def test_request_degrades_on_error(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(raise_exc=ConnectionError("boom")))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    out = client.get_json("/x")
    assert out["ok"] is False and "boom" in out["detail"]


# --- SSE ------------------------------------------------------------------
def test_stream_sse_parses_events(inject_requests):
    lines = ['data: {"event": "a", "n": 1}', "", "data: [DONE]"]
    inject_requests(lambda m, u, kw: _Resp(lines=lines))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    events = list(client.stream_sse("/run", {"goal": "x"}))
    assert events == [{"event": "a", "n": 1}]


def test_stream_sse_error_event(inject_requests):
    inject_requests(lambda m, u, kw: _Resp(raise_exc=ConnectionError("down")))
    client = VibeClient(VibeConfig.from_config(_Settings(), _cfg()))
    events = list(client.stream_sse("/run", {"goal": "x"}))
    assert len(events) == 1 and events[0]["ok"] is False
