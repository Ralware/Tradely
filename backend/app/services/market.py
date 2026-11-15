from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.core.config import Settings
from app.core.instruments import instrument_id_for, normalize_symbol, resolve_exchange
from app.providers.base import MarketDataProvider, ProviderError, normalize_candles
from app.providers.tradingview import TradingViewProvider

ALLOWED_PROVIDERS = {"auto", "tradingview"}


class _CandleCache:
    def __init__(self, max_entries: int = 128) -> None:
        self.max_entries = max_entries
        self._values: OrderedDict[tuple[object, ...], tuple[float, pd.DataFrame, str]] = OrderedDict()
        self._inflight: dict[tuple[object, ...], Future[tuple[pd.DataFrame, str]]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def get_or_load(
        self,
        key: tuple[object, ...],
        ttl_seconds: int,
        loader: Callable[[], tuple[pd.DataFrame, str]],
    ) -> tuple[pd.DataFrame, str]:
        with self._lock:
            now = time.monotonic()
            cached = self._values.get(key)
            if cached is not None:
                expires, frame, source = cached
                if expires > now:
                    self._values.move_to_end(key)
                    return frame.copy(), source
                self._values.pop(key, None)
            future = self._inflight.get(key)
            is_loader = future is None
            if future is None:
                future = Future()
                self._inflight[key] = future

        if not is_loader:
            frame, source = future.result()
            return frame.copy(), source

        try:
            frame, source = loader()
            with self._lock:
                self._values[key] = (
                    time.monotonic() + max(1, ttl_seconds), frame.copy(), source,
                )
                self._values.move_to_end(key)
                while len(self._values) > self.max_entries:
                    self._values.popitem(last=False)
            future.set_result((frame.copy(), source))
            return frame.copy(), source
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                if self._inflight.get(key) is future:
                    self._inflight.pop(key, None)


class MarketService:
    """Single TradingView-backed market-data service for every instrument."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.tradingview = TradingViewProvider(settings)
        self.cache = _CandleCache()

    def candles(
        self,
        symbol: str,
        *,
        market: str,
        exchange: str | None = None,
        interval: str = "1d",
        days: int = 365,
        provider: str = "auto",
        full_history: bool = True,
    ) -> tuple[pd.DataFrame, str]:
        if days < 1 or days > 3650:
            raise ValueError("days must be between 1 and 3650")
        if provider not in ALLOWED_PROVIDERS:
            raise ValueError("provider must be auto or tradingview")
        if full_history:
            # Ask TradingView for every bar it exposes for this timeframe.
            start = end = None
        else:
            end = datetime.now(timezone.utc).date()
            start = end - timedelta(days=days)
        canonical_id = instrument_id_for(
            normalize_symbol(symbol, market), market, resolve_exchange(market, exchange)
        )

        def fetch() -> tuple[pd.DataFrame, str]:
            adapter: MarketDataProvider = self.tradingview
            try:
                frame = adapter.fetch_candles(
                    symbol,
                    market=market,
                    exchange=exchange,
                    interval=interval,
                    start=start,
                    end=end,
                )
                frame = normalize_candles(frame)
                frame.attrs.setdefault("source", adapter.name)
                frame.attrs.setdefault("is_adjusted", adapter.is_adjusted)
                return frame, adapter.name
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(f"{adapter.name}: {exc}") from exc

        adapter = self.tradingview
        cache_key = (
            canonical_id, interval, adapter.is_adjusted,
            (adapter.__class__.__module__, adapter.__class__.__qualname__, adapter.name),
            start, end,
        )
        return self.cache.get_or_load(cache_key, self.settings.market_cache_seconds, fetch)

    # ------------------------------------------------------------------
    # Quotes and metadata (bridge-backed)
    # ------------------------------------------------------------------
    def quote(self, provider_symbol: str) -> dict[str, Any]:
        return self.tradingview.bridge.quote(provider_symbol)

    def quotes(self, provider_symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        return self.tradingview.quotes(provider_symbols)

    def symbol_info(self, provider_symbol: str) -> dict[str, Any]:
        return self.tradingview.symbol_info(provider_symbol)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.tradingview.search(query, limit=limit)

    def bridge_health(self) -> dict[str, Any]:
        return self.tradingview.bridge.health()
