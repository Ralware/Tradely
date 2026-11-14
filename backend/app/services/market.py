from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.core.config import Settings
from app.core.cache import TTLCache
from app.providers.base import ProviderError
from app.providers.market_data import BinanceSpotProvider, TejHQProvider, YahooFinanceProvider


class MarketService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tejhq = TejHQProvider(settings)
        self.yahoo = YahooFinanceProvider()
        self.binance = BinanceSpotProvider(settings)
        self.cache = TTLCache()

    def candles(self, symbol: str, *, market: str, exchange: str | None = None,
                interval: str = "1d", days: int = 365, provider: str = "auto") -> tuple[pd.DataFrame, str]:
        if days < 1 or days > 3650:
            raise ValueError("days must be between 1 and 3650")
        end = date.today()
        start = end - timedelta(days=days)
        cache_key = f"{market}|{exchange}|{symbol.upper()}|{interval}|{days}|{provider}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached_frame, cached_source = cached
            return cached_frame.copy(), cached_source
        errors: list[str] = []
        if provider not in {"auto", "tejhq", "yahoo", "binance"}:
            raise ValueError("provider must be auto, tejhq, yahoo or binance")
        compatible_provider = {"india": "tejhq", "global": "yahoo", "crypto": "binance"}[market]
        if provider != "auto" and provider != compatible_provider:
            raise ValueError(f"{provider} is not compatible with the {market} market; use {compatible_provider}")
        chain = []
        if provider == "tejhq":
            chain = [self.tejhq]
        elif provider == "yahoo":
            chain = [self.yahoo]
        elif provider == "binance":
            chain = [self.binance]
        elif market == "india":
            # India is always routed to TejHQ.  Raw candles remain visible when
            # no key is configured, but downstream signal/backtest safeguards
            # suppress actionable output until adjusted history is available.
            chain = [self.tejhq]
        elif market == "crypto":
            chain = [self.binance]
        else:
            chain = [self.yahoo]

        for adapter in chain:
            try:
                frame = adapter.fetch_candles(
                    symbol, market=market, exchange=exchange, interval=interval,
                    start=start, end=end,
                )
                if len(frame) < 1:
                    raise ProviderError("Provider returned zero valid candles")
                frame.attrs.setdefault("source", adapter.name)
                self.cache.set(cache_key, (frame.copy(), adapter.name), self.settings.market_cache_seconds)
                return frame, adapter.name
            except Exception as exc:
                errors.append(f"{adapter.name}: {exc}")
        raise ProviderError("All configured providers failed. " + " | ".join(errors))
