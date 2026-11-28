from __future__ import annotations

import calendar
import logging
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.core.config import Settings
from app.core.instruments import TRADINGVIEW_PROVIDER
from app.providers.base import (
    MarketDataProvider,
    ProviderError,
    normalize_candles,
)

# Tradely canonical interval -> TradingView bar resolution.
INTERVAL_TO_TIMEFRAME: dict[str, str] = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "45m": "45",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "8h": "480",
    "12h": "720",
    "1d": "D",
    "3d": "3D",
    "1wk": "W",
    "1mo": "M",
}

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "45m": 2700,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1wk": 604800,
    "1mo": 2592000,
}

logger = logging.getLogger(__name__)

_FRESHNESS_NOTE = (
    "TradingView is an unofficial community API; available delay depends on the "
    "exchange and account plan (anonymous NSE data is typically 15 minutes delayed)."
)

# The bridge/library pages deep history in 5,000-bar batches. This ceiling keeps
# a single request inside the bridge timeout while covering years of daily bars
# and weeks of minute bars. Callers can lower it through settings.
MAX_HISTORY_REQUEST = 1_000_000
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def price_metadata_from_symbol_info(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Translate TradingView ``pricescale``/``minmov`` into display precision.

    Values are presentation metadata only; candle prices are never rounded.
    """
    if not isinstance(payload, dict):
        return {}
    try:
        pricescale = int(payload.get("pricescale") or 0)
        minmov = int(payload.get("minmov") or 1)
    except (TypeError, ValueError):
        return {}
    if pricescale < 1 or minmov < 1:
        return {}
    precision = max(0, len(str(pricescale)) - 1)
    metadata: dict[str, Any] = {
        "price_scale": pricescale,
        "min_move": minmov / pricescale,
        "price_precision": precision,
        "min_move_units": minmov,
    }
    currency = payload.get("currency_code") or payload.get("currency")
    if currency:
        metadata["price_currency"] = str(currency).strip().upper()
    return metadata


def _iso_from_unix(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


class TradingViewBridge:
    """Loopback HTTP client for ``tradingview-bridge/server.mjs``."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.tradingview_bridge_url.rstrip("/")
        self._client = httpx.Client(trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        attempts = max(1, int(self.settings.tradingview_request_retries))
        backoff = max(0.0, float(self.settings.tradingview_retry_backoff_seconds))
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._client.get(
                    f"{self.base_url}{path}",
                    params=params,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= attempts:
                    break
                delay = backoff * (2 ** (attempt - 1))
                logger.warning(
                    "[TV] %s request failed (%s); retrying in %.1fs (attempt %d/%d)",
                    path, exc.__class__.__name__, delay, attempt, attempts,
                )
                if delay:
                    time.sleep(delay)
                continue

            if response.status_code in _RETRYABLE_STATUS and attempt < attempts:
                headers = getattr(response, "headers", {}) or {}
                retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
                delay = backoff * (2 ** (attempt - 1))
                try:
                    delay = min(30.0, max(delay, float(retry_after)))
                except (TypeError, ValueError):
                    pass
                logger.warning(
                    "[TV] %s returned HTTP %s; retrying in %.1fs (attempt %d/%d)",
                    path, response.status_code, delay, attempt, attempts,
                )
                if delay:
                    time.sleep(delay)
                continue

            if response.status_code >= 400:
                detail = ""
                try:
                    payload = response.json()
                    error = payload.get("error") if isinstance(payload, dict) else None
                    if isinstance(error, dict):
                        detail = str(error.get("message") or "")
                    elif error:
                        detail = str(error)
                except ValueError:
                    detail = (response.text or "")[:200]
                raise ProviderError(
                    f"TradingView bridge returned HTTP {response.status_code}"
                    + (f": {detail}" if detail else "")
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError("The TradingView bridge returned an unreadable response") from exc
            if not isinstance(payload, dict):
                raise ProviderError("The TradingView bridge returned an unexpected payload")
            return payload

        raise ProviderError(
            "The TradingView bridge is unavailable at "
            f"{self.base_url}. Start it with run.bat, run.sh, or "
            f"`npm start` in tradingview-bridge. ({last_error})"
        ) from last_error

    def health(self) -> dict[str, Any]:
        return self._request(
            "/health", timeout=min(10.0, self.settings.tradingview_bridge_timeout_seconds)
        )

    def candles(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: int | None = None,
        end: int | None = None,
        adjustment: str = "splits",
        count: int | None = None,
        max_count: int | None = None,
        bypass_cache: bool = False,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "adjustment": adjustment,
        }
        if bypass_cache:
            params["bypass_cache"] = "true"
        if start is not None or end is not None:
            if start is not None:
                params["from"] = start
            if end is not None:
                params["to"] = end
            if max_count is not None:
                params["maxCount"] = max_count
        else:
            # The bridge/library pages in batches until the requested count is
            # satisfied or TradingView has no older bars.
            params["count"] = count or max_count or MAX_HISTORY_REQUEST
            if max_count is not None:
                params["maxCount"] = max_count
        payload = self._request(
            "/candles",
            params,
            timeout=self.settings.tradingview_candles_timeout_seconds,
        )
        rows = payload.get("candles")
        if not isinstance(rows, list):
            raise ProviderError("TradingView bridge returned no candle list")
        return rows

    def quotes(self, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        if not symbols:
            return {}, {}
        payload = self._request(
            "/quotes",
            {"symbols": ",".join(symbols)},
            timeout=self.settings.tradingview_quotes_timeout_seconds,
        )
        quotes = payload.get("quotes")
        errors = payload.get("errors")
        if not isinstance(quotes, dict):
            raise ProviderError("TradingView bridge returned no quote map")
        return (
            {str(key): value for key, value in quotes.items() if isinstance(value, dict)},
            {str(key): str(value) for key, value in (errors or {}).items()}
            if isinstance(errors, dict)
            else {},
        )

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        payload = self._request(
            "/symbol",
            {"symbol": symbol},
            timeout=self.settings.tradingview_bridge_timeout_seconds,
        )
        info = payload.get("info")
        if not isinstance(info, dict):
            raise ProviderError(f"TradingView bridge returned no symbol metadata for {symbol}")
        return info

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._request(
            "/search",
            {"q": query, "limit": limit},
            timeout=self.settings.tradingview_search_timeout_seconds,
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ProviderError("TradingView bridge returned no search results")
        return [item for item in results if isinstance(item, dict)]


def _final_bar_is_forming(
    frame: pd.DataFrame, interval: str, market: str, *, now: pd.Timestamp | None = None
) -> bool:
    """Whether the newest bar's interval has not completed yet."""
    if frame.empty:
        return False
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    last = frame.index[-1]
    seconds = INTERVAL_SECONDS.get(interval)

    if market == "crypto" and interval in ("1wk", "1mo"):
        end = last + (pd.DateOffset(weeks=1) if interval == "1wk" else pd.offsets.MonthBegin(1))
        return now < end

    if interval == "1d":
        if market in {"india", "global"}:
            zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
            close_hour, close_minute = (15, 45) if market == "india" else (16, 5)
            last_local = last.tz_convert(zone)
            now_local = now.tz_convert(zone)
            return last_local.date() == now_local.date() and (
                now_local.hour, now_local.minute
            ) < (close_hour, close_minute)
        return last + pd.Timedelta(days=1) > now
    if interval == "3d":
        return last + pd.Timedelta(days=3) > now
    if interval == "1wk":
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        last_local = last.tz_convert(zone)
        now_local = now.tz_convert(zone)
        last_week = last_local.date() - timedelta(days=last_local.weekday())
        current_week = now_local.date() - timedelta(days=now_local.weekday())
        close_time = (15, 45) if market == "india" else (16, 5)
        week_complete = now_local.weekday() > 4 or (
            now_local.weekday() == 4 and (now_local.hour, now_local.minute) >= close_time
        )
        return last_week == current_week and not week_complete
    if interval == "1mo":
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        last_local = last.tz_convert(zone)
        now_local = now.tz_convert(zone)
        month_end = calendar.monthrange(now_local.year, now_local.month)[1]
        close_time = (15, 45) if market == "india" else (16, 5)
        month_complete = now_local.day == month_end and (
            now_local.hour, now_local.minute
        ) >= close_time
        return (
            (last_local.year, last_local.month) == (now_local.year, now_local.month)
            and not month_complete
        )
    if seconds is not None:
        return last + pd.Timedelta(seconds=seconds) > now
    return False


def _drop_incomplete_final_bar(
    frame: pd.DataFrame, interval: str, market: str, *, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Never expose a still-forming bar to signals, quotes or backtests."""
    if frame.empty:
        return frame
    return frame.iloc[:-1] if _final_bar_is_forming(frame, interval, market, now=now) else frame


class TradingViewProvider(MarketDataProvider):
    """Market data provider backed by the unofficial TradingView API bridge."""

    name = TRADINGVIEW_PROVIDER

    def __init__(self, settings: Settings):
        self.settings = settings
        self.bridge = TradingViewBridge(settings)

    @property
    def adjustment_status(self) -> str:
        # The bridge accepts an adjustment request but provides no independent
        # evidence that corporate-action adjustments were applied successfully.
        return "unknown"

    @property
    def is_adjusted(self) -> bool | None:
        return None

    def fetch_candles(
        self,
        symbol: str,
        *,
        market: str,
        exchange: str | None,
        interval: str,
        start: date | None,
        end: date | None,
        bypass_cache: bool = False,
    ) -> pd.DataFrame:
        timeframe = INTERVAL_TO_TIMEFRAME.get(interval)
        if timeframe is None:
            raise ProviderError(f"Unsupported TradingView interval: {interval}")
        if not exchange:
            raise ProviderError("TradingView requires an exchange-qualified symbol")
        tv_symbol = f"{exchange.upper()}:{symbol.upper()}"

        max_bars = max(1, int(self.settings.tradingview_history_max_bars))
        end_date = end or datetime.now(UTC).date()
        start_date = start or (end_date - timedelta(days=365 * 3))
        if start_date > end_date:
            raise ProviderError("History start date must be before the end date")

        if start is not None or end is not None:
            start_ts = int(pd.Timestamp(start_date, tz="UTC").timestamp())
            end_ts = int(pd.Timestamp(end_date + timedelta(days=1), tz="UTC").timestamp()) - 1
            rows = self.bridge.candles(
                tv_symbol,
                timeframe=timeframe,
                start=start_ts,
                end=end_ts,
                max_count=max_bars,
                bypass_cache=bypass_cache,
            )
        else:
            # Bounded deep history: the library pages in 5,000-bar batches and
            # stops at this ceiling instead of running into the bridge timeout.
            rows = self.bridge.candles(
                tv_symbol,
                timeframe=timeframe,
                count=max_bars,
                max_count=max_bars,
                bypass_cache=bypass_cache,
            )
        prepared = [
            {
                "timestamp": pd.to_datetime(row.get("time"), unit="s", utc=True, errors="coerce"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume", 0),
            }
            for row in rows
        ]
        frame = pd.DataFrame(prepared)
        if frame.empty:
            raise ProviderError(f"TradingView returned no candles for {tv_symbol}")
        frame = frame.dropna(subset=["timestamp"]).set_index("timestamp")
        if start is not None or end is not None:
            frame = frame.loc[
                (frame.index >= pd.Timestamp(start_date, tz="UTC"))
                & (frame.index < pd.Timestamp(end_date + timedelta(days=1), tz="UTC"))
            ]
        if frame.empty:
            raise ProviderError(
                f"TradingView returned no candles for {tv_symbol} in the requested range"
            )
        frame = normalize_candles(frame)
        forming = _final_bar_is_forming(frame, interval, market)
        forming_candle = None
        if forming:
            current = frame.iloc[-1]
            forming_candle = {
                "timestamp": frame.index[-1].isoformat(),
                "open": float(current["open"]),
                "high": float(current["high"]),
                "low": float(current["low"]),
                "close": float(current["close"]),
                "volume": float(current["volume"]),
            }
        frame = _drop_incomplete_final_bar(frame, interval, market)
        if frame.empty:
            raise ProviderError(
                "TradingView returned only an incomplete candle for this interval"
            )
        # A full batch means the provider may have more bars than the request
        # ceiling. Never present a capped response as complete history.
        history_truncated = bool(rows) and len(rows) >= max_bars
        frame.attrs["source"] = self.name
        frame.attrs["adjustment_status"] = "unknown"
        frame.attrs["is_adjusted"] = None
        frame.attrs["freshness"] = _FRESHNESS_NOTE
        frame.attrs["history_truncated"] = history_truncated
        frame.attrs["history_pages"] = math.ceil(len(rows) / 5000) if rows else 0
        frame.attrs["requested_bars"] = max_bars
        frame.attrs["provider_rows"] = len(rows)
        frame.attrs["provider_symbol"] = tv_symbol
        frame.attrs["candle_timeframe"] = timeframe
        # _drop_incomplete_final_bar removes the latest bar when its interval
        # has not completed. The final returned row is therefore confirmed, and
        # the exclusion is recorded so callers can distinguish the two states.
        frame.attrs["last_bar_confirmed"] = True
        frame.attrs["forming_bar_excluded"] = forming
        frame.attrs["forming_candle"] = forming_candle
        logger.info(
            "[TV] candles symbol=%s interval=%s rows=%d requested=%d truncated=%s forming=%s",
            tv_symbol, interval, len(frame), max_bars, history_truncated, forming,
        )
        return frame

    def quotes(self, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        return self.bridge.quotes(symbols)

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        return self.bridge.symbol_info(symbol)

    def price_metadata(self, symbol: str, exchange: str | None) -> dict[str, Any]:
        """Display precision from the provider's symbol metadata.

        The bridge caches symbol metadata for six hours, so this is a cheap
        lookup after the first request. Failure is non-fatal: callers fall back
        to the instrument's existing display rules.
        """
        if not exchange:
            return {}
        try:
            info = self.bridge.symbol_info(f"{exchange.upper()}:{symbol.upper()}")
        except ProviderError:
            return {}
        return price_metadata_from_symbol_info(info)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.bridge.search(query, limit=limit)
