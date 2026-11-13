from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8765
    database_path: str = "./data/tradely.sqlite3"
    tejhq_api_key: str = ""
    coingecko_api_key: str = ""
    sec_user_agent: str = "Tradely Private Research contact@example.invalid"
    gdelt_enabled: bool = True
    yahoo_news_enabled: bool = True
    rss_feed_urls: str = ""
    http_timeout_seconds: float = 15.0
    news_cache_seconds: int = 900
    market_cache_seconds: int = 300
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

    @property
    def rss_urls(self) -> list[str]:
        return [item.strip() for item in self.rss_feed_urls.split(",") if item.strip()]


@lru_cache

def get_settings() -> Settings:
    return Settings()
