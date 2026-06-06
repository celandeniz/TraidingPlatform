"""Environment + YAML config loading.

Secrets come from .env (never committed). Strategy/threshold config comes from
config.yaml. Keep these separate: .env = credentials, config.yaml = behaviour.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKEND_DIR.parent
CONFIG_PATH = BACKEND_DIR / "config.yaml"


class Settings(BaseSettings):
    """Credentials and runtime mode, read from .env / environment."""

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_feed: str = "iex"
    trading_mode: str = "paper"
    anthropic_api_key: str = ""
    live_trading: bool = False
    ccxt_api_key: str = ""
    ccxt_api_secret: str = ""
    ccxt_exchange: str = "binance"
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
def get_config() -> dict:
    """Parsed config.yaml as a plain dict."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
