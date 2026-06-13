"""Live Vibe sidecar smoke test — OFF by default.

Runs only when VIBE_SMOKE=1 and the sidecar answers its health probe. It hits a
real container to confirm our transport + adapters work against Vibe's actual
(undocumented) API. Never runs in default CI.

Usage:
    make vibe-up                       # start the sidecar (needs a clone + LLM key)
    VIBE_SMOKE=1 .venv/bin/python -m pytest backend/tests/test_vibe_integration_smoke.py -q
"""
import os

import pytest

from backend.integrations.vibe_trading import build_vibe_client
from backend.settings import get_config, get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("VIBE_SMOKE") != "1",
    reason="set VIBE_SMOKE=1 and run `make vibe-up` to exercise the live sidecar",
)


def _client_or_skip():
    cfg = get_config()
    # Force-enable for the smoke run regardless of config.yaml default.
    cfg = {**cfg, "vibe_trading": {**cfg.get("vibe_trading", {}), "enabled": True}}
    client = build_vibe_client(get_settings(), cfg)
    if client is None:
        pytest.skip("vibe sidecar not reachable (start it with `make vibe-up`)")
    return client


def test_health_reachable():
    client = _client_or_skip()
    assert client.health().get("ok") is True


def test_skills_listing():
    """A cheap read tool that needs no LLM call."""
    client = _client_or_skip()
    out = client.get_json("/skills")
    assert isinstance(out, dict) and out.get("ok") is not False


def test_research_round_trip():
    """Full advisory loop — needs an LLM provider key in the sidecar's agent.env."""
    client = _client_or_skip()
    from backend.integrations.vibe_trading import research_adapter as vr

    res = vr.run_research(client, "AAPL")
    # We assert the flow completes and returns our normalized shape; the actual
    # summary depends on the configured model.
    assert res.symbol == "AAPL"
    assert res.side in ("long", "short", "pass")
