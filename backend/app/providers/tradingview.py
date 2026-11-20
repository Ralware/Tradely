from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
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

_FRESHNESS_NOTE = (
    "TradingView is an unofficial community API; available delay depends on the "
    "exchange and account plan (anonymous NSE data is typically 15 minutes delayed)."
)

# The bridge/library pages deep history until TradingView stops returning bars.
# This is a request ceiling, not a Tradely display cap.
MAX_HISTORY_REQUEST = 1_000_000


def _iso_from_unix(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


class TradingViewBridge:
    """Loopback HTTP client for ``tradingview-bridge/server.mjs``."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.tradingview_bridge_url.rstrip("/")

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                "The TradingView bridge is unavailable at "
                f"{self.base_url}. Start it with run.bat, run.sh, or "
                f"`npm start` in tradingview-bridge. ({exc})"
            ) from exc
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
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "adjustment": adjustment,
        }
        if start is not None or end is not None:
            if start is not None:
                params["from"] = start
            if end is not None:
                params["to"] = end
        else:
            # The bridge/library pages until TradingView has no older bars.
            params["count"] = MAX_HISTORY_REQUEST
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


def _drop_incomplete_final_bar(
    frame: pd.DataFrame, interval: str, market: str, *, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Never expose a still-forming bar to signals, quotes or backtests."""
    if frame.empty:
        return frame
    now = pd.Timestamp.now(tz="UTC") if now is None else now
    last = frame.index[-1]
    seconds = INTERVAL_SECONDS.get(interval)

    if market == "crypto" and interval in ("1wk", "1mo"):
        end = last + (pd.DateOffset(weeks=1) if interval == "1wk" else pd.offsets.MonthBegin(1))
        return frame.iloc[:-1] if now < end else frame

    if market == "crypto" and interval in ("1wk", "1mo"):
        end = last + (pd.DateOffset(weeks=1) if interval == "1wk" else pd.offsets.MonthBegin(1))
        return frame.iloc[:-1] if now < end else frame

    if interval == "1d":
        if market in {"india", "global"}:
            zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
            close_hour, close_minute = (15, 45) if market == "india" else (16, 5)
            last_local = last.tz_convert(zone)
            now_local = now.tz_convert(zone)
            if last_local.date() == now_local.date() and (
                now_local.hour, now_local.minute
            ) < (close_hour, close_minute):
                frame = frame.iloc[:-1]
        elif last + pd.Timedelta(days=1) > now:
            frame = frame.iloc[:-1]
    elif interval == "1wk":
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        last_local = last.tz_convert(zone)
        now_local = now.tz_convert(zone)
        last_week = last_local.date() - timedelta(days=last_local.weekday())
        current_week = now_local.date() - timedelta(days=now_local.weekday())
        close_time = (15, 45) if market == "india" else (16, 5)
        week_complete = now_local.weekday() > 4 or (
            now_local.weekday() == 4 and (now_local.hour, now_local.minute) >= close_time
        )
        if last_week == current_week and not week_complete:
            frame = frame.iloc[:-1]
    elif interval == "1mo":
        zone = ZoneInfo("Asia/Kolkata" if market == "india" else "America/New_York")
        last_local = last.tz_convert(zone)
        now_local = now.tz_convert(zone)
        month_end = calendar.monthrange(now_local.year, now_local.month)[1]
        close_time = (15, 45) if market == "india" else (16, 5)
        month_complete = now_local.day == month_end and (
            now_local.hour, now_local.minute
        ) >= close_time
        if (last_local.year, last_local.month) == (now_local.year, now_local.month) and not month_complete:
            frame = frame.iloc[:-1]
    elif seconds is not None:
        if last + pd.Timedelta(seconds=seconds) > now:
            frame = frame.iloc[:-1]
    return frame


class TradingViewProvider(MarketDataProvider):
    """Market data provider backed by the unofficial TradingView API bridge."""

    name = TRADINGVIEW_PROVIDER

    def __init__(self, settings: Settings):
        self.settings = settings
        self.bridge = TradingViewBridge(settings)

    @property
    def is_adjusted(self) -> bool:
        return True

    def fetch_candles(
        self,
        symbol: str,
        *,
        market: str,
        exchange: str | None,
        interval: str,
        start: date | None,
        end: date | None,
    ) -> pd.DataFrame:
        timeframe = INTERVAL_TO_TIMEFRAME.get(interval)
        if timeframe is None:
            raise ProviderError(f"Unsupported TradingView interval: {interval}")
        if not exchange:
            raise ProviderError("TradingView requires an exchange-qualified symbol")
        tv_symbol = f"{exchange.upper()}:{symbol.upper()}"

        end_date = end or datetime.now(timezone.utc).date()
        start_date = start or (end_date - timedelta(days=365 * 3))
        if start_date > end_date:
            raise ProviderError("History start date must be before the end date")

        if start is not None or end is not None:
            start_ts = int(pd.Timestamp(start_date, tz="UTC").timestamp())
            end_ts = int(pd.Timestamp(end_date + timedelta(days=1), tz="UTC").timestamp()) - 1
            rows = self.bridge.candles(
                tv_symbol, timeframe=timeframe, start=start_ts, end=end_ts
            )
        else:
            # Maximum available history for this symbol/timeframe.
            rows = self.bridge.candles(tv_symbol, timeframe=timeframe)
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
        frame = _drop_incomplete_final_bar(frame, interval, market)
        if frame.empty:
            raise ProviderError(
                "TradingView returned only an incomplete candle for this interval"
            )
        frame.attrs["source"] = self.name
        frame.attrs["is_adjusted"] = True
        frame.attrs["freshness"] = _FRESHNESS_NOTE
        frame.attrs["history_truncated"] = False
        frame.attrs["provider_symbol"] = tv_symbol
        frame.attrs["candle_timeframe"] = timeframe
        return frame

    def quotes(self, symbols: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        return self.bridge.quotes(symbols)

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        return self.bridge.symbol_info(symbol)

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.bridge.search(query, limit=limit)
