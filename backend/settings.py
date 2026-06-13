"""Environment + YAML config loading.

Secrets come from .env (never committed). Strategy/threshold config comes from
config.yaml. Keep these separate: .env = credentials, config.yaml = behaviour.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .profiles import apply_active_profile

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent
CONFIG_PATH = BACKEND_DIR / "config.yaml"


class Settings(BaseSettings):
    """Credentials and runtime mode, read from .env / environment."""

    alpaca_api_key: str = ""
    alpaca_api_secret: str = Field(
        default="", validation_alias=AliasChoices("ALPACA_SECRET_KEY", "ALPACA_API_SECRET")
    )
    alpaca_paper_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        validation_alias=AliasChoices("ALPACA_BASE_URL", "ALPACA_PAPER_BASE_URL"),
    )
    alpaca_data_feed: str = "iex"
    trading_mode: str = "paper"
    profile: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""        # Gemini (research.llm.provider=gemini)
    gemini_api_key: str = ""        # alias accepted for the same key
    deepseek_api_key: str = ""      # OpenAI-compatible (research.llm.provider=deepseek)
    openai_api_key: str = ""        # OpenAI-compatible (provider=openai)
    openai_base_url: str = ""       # override compat endpoint (DashScope/SiliconFlow/…)
    live_trading: bool = False
    ccxt_api_key: str = ""
    ccxt_api_secret: str = Field(
        default="", validation_alias=AliasChoices("CCXT_SECRET_KEY", "CCXT_API_SECRET")
    )
    ccxt_exchange: str = "binance"
    # Vibe-Trading sidecar bearer token (only needed if its :8899 is exposed
    # beyond loopback; sent as the API_AUTH_KEY header). See deploy/vibe-trading/.
    vibe_api_auth_key: str = ""
    # Optional OpenBB market-data provider keys (only used when marketdata.enabled).
    fmp_api_key: str = ""
    polygon_api_key: str = ""
    intrinio_api_key: str = ""
    tiingo_token: str = ""
    alpha_vantage_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_raw_config() -> dict:
    """Parsed config.yaml before profile overlays."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def get_config() -> dict:
    """Parsed config.yaml as a plain dict with the active profile merged in."""
    return apply_active_profile(get_raw_config())
