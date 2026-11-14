from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8765
    database_path: str = "./data/tradely.sqlite3"
    tejhq_api_key: str = ""
    gdelt_enabled: bool = True
    yahoo_news_enabled: bool = True
    http_timeout_seconds: float = 15.0
    news_cache_seconds: int = 900
    market_cache_seconds: int = 300
    quote_crypto_ttl_seconds: int = 10
    quote_global_ttl_seconds: int = 300
    quote_india_ttl_seconds: int = 600
    quote_backoff_base_seconds: int = 5
    quote_backoff_max_seconds: int = 300
    quote_rules_ttl_seconds: int = 86400
    quote_stream_interval_seconds: float = 2.0
    binance_stream_enabled: bool = True
    default_account_currency: str = "INR"
    default_risk_fraction: float = 0.005
    max_risk_fraction: float = 0.02

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_file(self) -> Path:
        path = Path(self.database_path).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

@lru_cache

def get_settings() -> Settings:
    return Settings()
