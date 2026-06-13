"""Vibe-Trading sidecar integration.

Our backend (Python 3.9) consumes the containerized HKUDS/Vibe-Trading sidecar
(Python 3.11+, :8899) over HTTP. Nothing from Vibe is installed in-process.

Public surface:
  * build_vibe_client(settings, cfg) -> VibeClient | None  (config-gated + health-checked)
  * VibeClient                                              (defensive HTTP transport)
  * VibeConfig                                              (frozen config view)
"""
from .client import VibeClient
from .config import VibeConfig
from .factory import build_vibe_client

__all__ = ["VibeClient", "VibeConfig", "build_vibe_client"]
