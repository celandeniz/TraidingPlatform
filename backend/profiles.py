"""Account/config profile loading.

Profiles are config overlays: the selected profile is validated, normalized,
and deep-merged over the base YAML config. Secrets remain environment-only.
"""
from __future__ import annotations

import copy
import os
from typing import Mapping

VALID_MODES = {"test", "live"}
VALID_BROKERS = {"alpaca_paper", "alpaca_live", "ccxt_sandbox", "ccxt_live", "mock", "ib"}

_active_profile_override: str | None = None

_PROFILE_META_KEYS = {"name", "mode", "broker", "executor", "features"}


def set_active_profile(name: str | None) -> None:
    """Set the active profile for the current Python process."""
    global _active_profile_override
    _active_profile_override = name


def get_active_profile_override() -> str | None:
    return _active_profile_override


def deep_merge(base: dict, override: Mapping) -> dict:
    """Return ``base`` recursively merged with ``override``; override wins."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def resolve_active_profile(raw_config: dict, env: Mapping[str, str] | None = None) -> str | None:
    """Resolve active profile: in-process override -> env -> config -> test."""
    profiles = raw_config.get("profiles")
    if not profiles:
        return None
    env_map = env if env is not None else os.environ
    return (
        _active_profile_override
        or env_map.get("PROFILE")
        or raw_config.get("active_profile")
        or "test"
    )


def _validate_profile(name: str, profile: Mapping) -> None:
    mode = profile.get("mode")
    if mode is not None and mode not in VALID_MODES:
        raise ValueError(
            f"Unknown mode for profile '{name}': {mode!r}. "
            f"Expected one of {sorted(VALID_MODES)}."
        )
    broker = profile.get("broker", profile.get("executor"))
    if broker is not None and broker not in VALID_BROKERS:
        raise ValueError(
            f"Unknown broker for profile '{name}': {broker!r}. "
            f"Expected one of {sorted(VALID_BROKERS)}."
        )


def _feature_overlay(features: Mapping | None) -> dict:
    if not features:
        return {}
    out: dict = {}
    if "research" in features:
        out.setdefault("research", {})["enabled"] = bool(features["research"])
    if "committee" in features:
        out.setdefault("research", {}).setdefault("committee", {})["enabled"] = bool(
            features["committee"]
        )
    if "auto_trader" in features:
        out.setdefault("auto_trader", {})["enabled"] = bool(features["auto_trader"])
    if "marketdata_backend" in features:
        out.setdefault("marketdata", {})["backend"] = features["marketdata_backend"]
        out.setdefault("marketdata", {})["enabled"] = bool(features["marketdata_backend"])
    if "news_rss" in features:
        out.setdefault("news_rss", {})["enabled"] = bool(features["news_rss"])
    if "perspective" in features:
        out.setdefault("perspective", {})["enabled"] = bool(features["perspective"])
    if "reflection" in features:
        out.setdefault("reflection", {})["enabled"] = bool(features["reflection"])
    if "realistic_fills" in features:
        out.setdefault("execution", {})["realistic_fills"] = bool(features["realistic_fills"])
    return out


def _broker_overlay(broker: str | None) -> dict:
    if broker is None:
        return {}
    if broker == "mock":
        return {"brokers": {"executor": "mock"}}
    if broker == "ib":
        return {"brokers": {"equity": {"executor": "ib"}}}
    if broker == "alpaca_paper":
        return {"brokers": {"equity": {"executor": "alpaca_paper"}}}
    if broker == "alpaca_live":
        return {"brokers": {"equity": {"executor": "alpaca_live"}}}
    if broker == "ccxt_sandbox":
        return {"brokers": {"crypto": {"executor": "ccxt_sandbox", "sandbox": True}}}
    if broker == "ccxt_live":
        return {"brokers": {"crypto": {"executor": "ccxt_live", "sandbox": False}}}
    return {}


def normalize_profile(name: str, profile: Mapping) -> dict:
    """Convert profile shortcuts into the normal config namespace shape."""
    _validate_profile(name, profile)
    overlay = {k: v for k, v in profile.items() if k not in _PROFILE_META_KEYS}
    broker = profile.get("broker", profile.get("executor"))
    overlay = deep_merge(overlay, _broker_overlay(broker))
    overlay = deep_merge(overlay, _feature_overlay(profile.get("features")))
    meta = {
        "name": profile.get("name", name),
        "mode": profile.get("mode", "test"),
        "broker": broker or "",
    }
    overlay["profile"] = meta
    return overlay


def apply_active_profile(raw_config: dict, env: Mapping[str, str] | None = None) -> dict:
    """Apply the resolved profile overlay to a raw parsed config dict."""
    base = copy.deepcopy(raw_config or {})
    profiles = base.get("profiles")
    if not profiles:
        return base
    active = resolve_active_profile(base, env=env)
    if active not in profiles:
        raise ValueError(
            f"Unknown active profile {active!r}. Available profiles: {sorted(profiles)}."
        )
    profile_overlay = normalize_profile(active, profiles[active] or {})
    merged = deep_merge(base, profile_overlay)
    merged["active_profile"] = active
    return merged


def feature_toggles(config: Mapping) -> dict:
    """Public, secret-free feature summary for a merged config."""
    return {
        "research": bool(config.get("research", {}).get("enabled", False)),
        "committee": bool(config.get("research", {}).get("committee", {}).get("enabled", False)),
        "auto_trader": bool(config.get("auto_trader", {}).get("enabled", False)),
        "marketdata_backend": config.get("marketdata", {}).get("backend"),
        "news_rss": bool(config.get("news_rss", {}).get("enabled", False)),
        "perspective": bool(config.get("perspective", {}).get("enabled", False)),
        "reflection": bool(config.get("reflection", {}).get("enabled", False)),
        "realistic_fills": bool(config.get("execution", {}).get("realistic_fills", False)),
    }


def profile_summaries(raw_or_merged_config: dict) -> list[dict]:
    """Return secret-free profile summaries for API/UI display."""
    profiles = raw_or_merged_config.get("profiles") or {}
    base = copy.deepcopy(raw_or_merged_config)
    out = []
    for name, profile in profiles.items():
        merged = deep_merge(base, normalize_profile(name, profile or {}))
        out.append(
            {
                "name": name,
                "mode": merged.get("profile", {}).get("mode", "test"),
                "broker": merged.get("profile", {}).get("broker", ""),
                "features": feature_toggles(merged),
            }
        )
    return out
