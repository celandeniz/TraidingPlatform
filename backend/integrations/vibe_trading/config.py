"""Frozen view of the `vibe_trading:` config namespace + the bearer secret.

Behaviour comes from config.yaml (base_url, timeouts, per-purpose toggles); the
optional bearer token comes from settings (.env). Keeping this in one dataclass
means the client and factory never re-parse raw config.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VibeConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8899"
    health_path: str = "/"
    request_timeout: float = 60.0
    health_timeout: float = 2.0
    committee_hook: bool = False
    purposes: dict = field(default_factory=dict)
    api_auth_key: str = ""

    @classmethod
    def from_config(cls, settings, cfg: dict) -> "VibeConfig":
        v = (cfg or {}).get("vibe_trading", {}) or {}
        return cls(
            enabled=bool(v.get("enabled", False)),
            base_url=str(v.get("base_url", "http://127.0.0.1:8899")).rstrip("/"),
            health_path=str(v.get("health_path", "/")),
            request_timeout=float(v.get("request_timeout", 60.0)),
            health_timeout=float(v.get("health_timeout", 2.0)),
            committee_hook=bool(v.get("committee_hook", False)),
            purposes=dict(v.get("purposes", {}) or {}),
            api_auth_key=getattr(settings, "vibe_api_auth_key", "") or "",
        )

    def purpose_enabled(self, name: str) -> bool:
        """Is a given purpose (research/strategy/execution) turned on?"""
        return bool(self.purposes.get(name, False))

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def headers(self) -> dict:
        """Auth header when a bearer token is configured (non-loopback deploys)."""
        if self.api_auth_key:
            return {"Authorization": f"Bearer {self.api_auth_key}"}
        return {}
