from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from datetime import date, timedelta

import pandas as pd

from app.core.config import Settings
from app.core.instruments import instrument_id_for, normalize_symbol, resolve_exchange
from app.providers.base import MarketDataProvider, ProviderError, normalize_candles
from app.providers.market_data import BinanceSpotProvider, TejHQProvider, YahooFinanceProvider


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
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tejhq = TejHQProvider(settings)
        self.yahoo = YahooFinanceProvider()
        self.binance = BinanceSpotProvider(settings)
        self.cache = _CandleCache()

    def candles(self, symbol: str, *, market: str, exchange: str | None = None,
                interval: str = "1d", days: int = 365, provider: str = "auto") -> tuple[pd.DataFrame, str]:
        if days < 1 or days > 3650:
            raise ValueError("days must be between 1 and 3650")
        end = date.today()
        start = end - timedelta(days=days)
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

        canonical_id = instrument_id_for(
            normalize_symbol(symbol, market), market, resolve_exchange(market, exchange)
        )

        def fetch() -> tuple[pd.DataFrame, str]:
            errors: list[str] = []
            for adapter in chain:
                try:
                    frame = adapter.fetch_candles(
                        symbol, market=market, exchange=exchange, interval=interval,
                        start=start, end=end,
                    )
                    frame = normalize_candles(frame, max_candles=adapter.max_history_candles)
                    frame.attrs.setdefault("source", adapter.name)
                    frame.attrs.setdefault("is_adjusted", adapter.is_adjusted)
                    return frame, adapter.name
                except Exception as exc:
                    errors.append(f"{adapter.name}: {exc}")
            raise ProviderError("All configured providers failed. " + " | ".join(errors))

        adapter: MarketDataProvider = chain[0]
        cache_key = (
            canonical_id, interval, adapter.is_adjusted,
            (adapter.__class__.__module__, adapter.__class__.__qualname__, adapter.name),
            start, end,
        )
        return self.cache.get_or_load(cache_key, self.settings.market_cache_seconds, fetch)
