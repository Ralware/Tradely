from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from app.core.config import Settings
from app.core.instruments import instrument_id_for, normalize_symbol, resolve_exchange
from app.providers.base import MarketDataProvider, ProviderError, normalize_candles
from app.providers.tradingview import INTERVAL_SECONDS, TradingViewProvider

logger = logging.getLogger(__name__)

ALLOWED_PROVIDERS = {"auto", "tradingview"}
_METADATA_TTL_SECONDS = 6 * 60 * 60
_TAIL_LOOKBACK_DAYS = {
    "1m": 2,
    "3m": 2,
    "5m": 2,
    "15m": 3,
    "30m": 4,
    "45m": 4,
    "1h": 5,
    "2h": 7,
    "4h": 10,
    "6h": 14,
    "8h": 18,
    "12h": 21,
    "1d": 10,
    "3d": 21,
    "1wk": 42,
    "1mo": 90,
}


@dataclass
class _CacheValue:
    expires: float
    loaded_at: float
    frame: pd.DataFrame
    source: str


def _merge_candles(base: pd.DataFrame, tail: pd.DataFrame) -> pd.DataFrame:
    """Merge an incremental tail into cached history without duplicate bars."""
    if base is None or base.empty:
        return normalize_candles(tail)
    if tail is None or tail.empty:
        return base.copy()
    truncated = bool(base.attrs.get("history_truncated")) or bool(
        tail.attrs.get("history_truncated")
    )
    combined = pd.concat([base, tail])
    combined.attrs.update({**base.attrs, **tail.attrs})
    merged = normalize_candles(combined)
    merged.attrs["history_truncated"] = truncated
    merged.attrs["forming_bar_excluded"] = bool(
        tail.attrs.get("forming_bar_excluded", base.attrs.get("forming_bar_excluded", False))
    )
    return merged


class _CandleCache:
    """Small LRU cache with request coalescing and incremental tail refresh.

    Historical rows are reused for the full TTL. When the entry is older than
    ``refresh_after_seconds`` the caller's ``refresher`` fetches only the newest
    window and merges it, so a chart is not pinned to the full cache TTL.
    """

    def __init__(self, max_entries: int = 128) -> None:
        self.max_entries = max_entries
        self._values: OrderedDict[tuple[object, ...], _CacheValue] = OrderedDict()
        self._inflight: dict[tuple[object, ...], Future[tuple[pd.DataFrame, str]]] = {}
        self._refreshing: set[tuple[object, ...]] = set()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def get_or_load(
        self,
        key: tuple[object, ...],
        ttl_seconds: int,
        loader: Callable[[], tuple[pd.DataFrame, str]],
        *,
        refresh_after_seconds: int | None = None,
        refresher: Callable[[pd.DataFrame], tuple[pd.DataFrame, str]] | None = None,
    ) -> tuple[pd.DataFrame, str]:
        now = time.monotonic()
        base_frame: pd.DataFrame | None = None
        base_source = ""
        is_loader = False

        with self._lock:
            cached = self._values.get(key)
            if cached is not None and cached.expires > now:
                self._values.move_to_end(key)
                should_refresh = (
                    refresher is not None
                    and refresh_after_seconds is not None
                    and now - cached.loaded_at >= max(0, refresh_after_seconds)
                    and key not in self._refreshing
                )
                if not should_refresh:
                    return cached.frame.copy(), cached.source
                self._refreshing.add(key)
                base_frame = cached.frame
                base_source = cached.source
            elif cached is not None:
                self._values.pop(key, None)

            if base_frame is None:
                future = self._inflight.get(key)
                is_loader = future is None
                if future is None:
                    future = Future()
                    self._inflight[key] = future

        if base_frame is not None and refresher is not None:
            try:
                tail, source = refresher(base_frame)
                merged = _merge_candles(base_frame, tail)
                with self._lock:
                    self._values[key] = _CacheValue(
                        expires=time.monotonic() + max(1, ttl_seconds),
                        loaded_at=time.monotonic(),
                        frame=merged,
                        source=source or base_source,
                    )
                    self._values.move_to_end(key)
                    while len(self._values) > self.max_entries:
                        self._values.popitem(last=False)
                return merged.copy(), source or base_source
            except Exception as exc:  # keep serving the last good history
                logger.warning("[MARKET] incremental refresh failed key=%s: %s", key, exc)
                # Back off until the next refresh window instead of retrying a
                # failing provider on every request.
                with self._lock:
                    current = self._values.get(key)
                    if current is not None:
                        self._values[key] = _CacheValue(
                            expires=current.expires,
                            loaded_at=time.monotonic(),
                            frame=current.frame,
                            source=current.source,
                        )
                return base_frame.copy(), base_source
            finally:
                with self._lock:
                    self._refreshing.discard(key)

        if not is_loader:
            frame, source = future.result()
            return frame.copy(), source

        try:
            frame, source = loader()
            with self._lock:
                self._values[key] = _CacheValue(
                    expires=time.monotonic() + max(1, ttl_seconds),
                    loaded_at=time.monotonic(),
                    frame=frame.copy(),
                    source=source,
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
        self._metadata: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._metadata_lock = threading.Lock()

    def _refresh_after_seconds(self, interval: str) -> int:
        configured = max(1, int(self.settings.market_latest_refresh_seconds))
        seconds = INTERVAL_SECONDS.get(interval)
        if seconds is None:
            return configured
        # Refresh often enough for intraday charts, but keep it well inside the
        # cache TTL so deep history is reused and only the tail is fetched.
        return max(configured, min(120, seconds // 4))

    def _tail_start(self, interval: str, last_timestamp: pd.Timestamp) -> date:
        days = _TAIL_LOOKBACK_DAYS.get(interval, 10)
        return (last_timestamp - timedelta(days=days)).date()

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
        bypass_cache: bool = False,
    ) -> tuple[pd.DataFrame, str]:
        if days < 1 or days > 3650:
            raise ValueError("days must be between 1 and 3650")
        if provider not in ALLOWED_PROVIDERS:
            raise ValueError("provider must be auto or tradingview")
        if full_history:
            # Ask for bounded deep history; the provider caps the request so a
            # symbol with millions of minute bars cannot time out the bridge.
            start = end = None
        else:
            end = datetime.now(UTC).date()
            start = end - timedelta(days=days)
        canonical_id = instrument_id_for(
            normalize_symbol(symbol, market), market, resolve_exchange(market, exchange)
        )
        adapter: MarketDataProvider = self.tradingview
        max_bars = max(1, int(self.settings.tradingview_history_max_bars))

        def fetch() -> tuple[pd.DataFrame, str]:
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

        def refresh_tail(cached: pd.DataFrame) -> tuple[pd.DataFrame, str]:
            if cached.empty:
                return fetch()
            tail_start = self._tail_start(interval, cached.index[-1])
            tail = adapter.fetch_candles(
                symbol,
                market=market,
                exchange=exchange,
                interval=interval,
                start=tail_start,
                end=None,
            )
            tail = normalize_candles(tail)
            tail.attrs.setdefault("source", adapter.name)
            tail.attrs.setdefault("is_adjusted", adapter.is_adjusted)
            return tail, adapter.name

        if bypass_cache:
            return fetch()
        cache_key = (
            canonical_id, interval, adapter.is_adjusted,
            (adapter.__class__.__module__, adapter.__class__.__qualname__, adapter.name),
            start, end, max_bars,
        )
        return self.cache.get_or_load(
            cache_key,
            self.settings.market_cache_seconds,
            fetch,
            refresh_after_seconds=self._refresh_after_seconds(interval),
            refresher=refresh_tail,
        )

    def price_metadata(self, symbol: str, exchange: str | None) -> dict[str, Any]:
        """Provider display precision, cached separately from candle data."""
        if not exchange:
            return {}
        key = (exchange.upper(), symbol.upper())
        now = time.monotonic()
        with self._metadata_lock:
            cached = self._metadata.get(key)
            if cached is not None and cached[0] > now:
                return dict(cached[1])
        metadata = self.tradingview.price_metadata(symbol, exchange)
        # Cache successful metadata for hours; retry missing metadata sooner so
        # a transient bridge failure does not pin the wrong precision.
        ttl = _METADATA_TTL_SECONDS if metadata else 300
        with self._metadata_lock:
            self._metadata[key] = (now + ttl, dict(metadata))
        return dict(metadata)

    # ------------------------------------------------------------------
    # Quotes and metadata (bridge-backed)
    # ------------------------------------------------------------------
    def quotes(self, provider_symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        return self.tradingview.quotes(provider_symbols)

    def symbol_info(self, provider_symbol: str) -> dict[str, Any]:
        return self.tradingview.symbol_info(provider_symbol)

    def bridge_health(self) -> dict[str, Any]:
        return self.tradingview.bridge.health()
