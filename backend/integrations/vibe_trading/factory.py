"""build_vibe_client — config-gated, health-checked builder.

Returns None unless vibe_trading.enabled is true AND the sidecar answers its
health probe, exactly like build_market_data_provider / llm_factory._try_ollama.
Callers treat None as "feature off / unreachable" and degrade.
"""
from __future__ import annotations

from typing import Optional

from .client import VibeClient
from .config import VibeConfig


def build_vibe_client(settings, cfg: dict) -> Optional[VibeClient]:
    vconf = VibeConfig.from_config(settings, cfg)
    if not vconf.enabled:
        return None
    client = VibeClient(vconf)
    if not client.health().get("ok"):
        return None
    return client
