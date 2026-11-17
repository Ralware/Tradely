from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    database_path: str = "./data/tradely.sqlite3"

    # The unofficial TradingView API runs in a local Node.js bridge because the
    # library is ESM/Node while this backend is Python.
    tradingview_bridge_url: str = "http://127.0.0.1:8010"
    tradingview_bridge_timeout_seconds: float = 60.0
    tradingview_candles_timeout_seconds: float = 50.0
    tradingview_quotes_timeout_seconds: float = 30.0
    tradingview_search_timeout_seconds: float = 15.0
    tradingview_live_search_enabled: bool = True

    market_cache_seconds: int = 300
    quote_crypto_ttl_seconds: int = 10
    quote_global_ttl_seconds: int = 300
    quote_india_ttl_seconds: int = 600
    quote_backoff_base_seconds: int = 5
    quote_backoff_max_seconds: int = 300
    quote_stream_interval_seconds: float = 5.0

    default_account_currency: str = "INR"
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
