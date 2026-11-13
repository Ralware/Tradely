from __future__ import annotations

import httpx

from app.core.config import Settings
from app.providers.base import ProviderError


class CoinGeckoProvider:
    name = "CoinGecko Demo"
    base_url = "https://api.coingecko.com/api/v3"

    def __init__(self, settings: Settings):
        self.settings = settings

    def markets(self, symbols: list[str] | None = None, currency: str = "usd") -> list[dict]:
        if not self.settings.coingecko_api_key:
            raise ProviderError("CoinGecko Demo API key is not configured")
        params = {"vs_currency": currency.lower(), "order": "market_cap_desc", "per_page": 100,
                  "page": 1, "sparkline": "false"}
        headers = {"x-cg-demo-api-key": self.settings.coingecko_api_key}
        try:
            response = httpx.get(f"{self.base_url}/coins/markets", params=params, headers=headers,
                                 timeout=self.settings.http_timeout_seconds)
            response.raise_for_status()
            rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"CoinGecko request failed: {exc}") from exc
        if symbols:
            wanted = {item.lower() for item in symbols}
            rows = [item for item in rows if item.get("symbol", "").lower() in wanted]
        return rows
