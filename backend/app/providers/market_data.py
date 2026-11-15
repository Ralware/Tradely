from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from app.core.config import Settings
from app.providers.base import (
    MAX_HISTORY_CANDLES,
    MarketDataProvider,
    ProviderError,
    normalize_candles,
)


def _to_frame(
    rows: list[dict[str, Any]],
    source: str,
    adjusted: bool = False,
    max_candles: int = MAX_HISTORY_CANDLES,
) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ProviderError(f"{source} returned no candles")
    rename = {
        "date": "timestamp", "datetime": "timestamp", "time": "timestamp",
        "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume",
    }
    frame = frame.rename(columns=rename)
    required = ["timestamp", "open", "high", "low", "close"]
    if not all(column in frame.columns for column in required):
        raise ProviderError(f"{source} response missing required OHLC fields")
    if "volume" not in frame.columns:
        frame["volume"] = 0
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=required).set_index("timestamp")
    frame.attrs["source"] = source
    frame.attrs["is_adjusted"] = adjusted
    if frame.empty:
        raise ProviderError(f"{source} returned no valid OHLC candles")
    return normalize_candles(frame, max_candles=max_candles)


class TejHQProvider(MarketDataProvider):
    name = "TejHQ"
    base_url = "https://api.tejhq.dev"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_adjusted(self) -> bool:
        return bool(self.settings.tejhq_api_key)

    def fetch_candles(self, symbol: str, *, market: str, exchange: str | None,
                      interval: str, start: date | None, end: date | None) -> pd.DataFrame:
        if market != "india":
            raise ProviderError("TejHQ only provides Indian market data")
        if interval != "1d":
            raise ProviderError("TejHQ adapter currently exposes daily EOD candles only")
        exchange_code = (exchange or "NSE").lower()
        if exchange_code not in {"nse", "bse"}:
            raise ProviderError("TejHQ exchange must be NSE or BSE")
        end_date = end or date.today()
        start_date = start or (end_date - timedelta(days=365 * 3))
        path = "adjusted" if self.settings.tejhq_api_key else "ohlcv"
        url = f"{self.base_url}/v1/{path}/{exchange_code}/{symbol.upper()}"
        headers = {}
        if self.settings.tejhq_api_key:
            headers["Authorization"] = f"Bearer {self.settings.tejhq_api_key}"
        try:
            response = httpx.get(
                url, params={"from": start_date.isoformat(), "to": end_date.isoformat()},
                headers=headers, timeout=self.settings.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"TejHQ request failed: {exc}") from exc
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        frame = _to_frame(rows, self.name, adjusted=path == "adjusted")
        frame.attrs["source"] = self.name
        frame.attrs["is_adjusted"] = path == "adjusted"
        frame.attrs["freshness"] = "end_of_day"
        return frame


class YahooFinanceProvider(MarketDataProvider):
    name = "Yahoo Finance (yfinance; unofficial)"
    supported_intervals = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
    max_lookback_days = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730}

    @property
    def is_adjusted(self) -> bool:
        return True

    def fetch_candles(self, symbol: str, *, market: str, exchange: str | None,
                      interval: str, start: date | None, end: date | None) -> pd.DataFrame:
        if interval not in self.supported_intervals:
            raise ProviderError(f"Unsupported Yahoo Finance interval: {interval}")
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderError("yfinance is not installed; run pip install -e .") from exc
        ticker = symbol.upper()
        if market == "india" and not ticker.endswith((".NS", ".BO")):
            ticker = ticker + (".BO" if (exchange or "NSE").upper() == "BSE" else ".NS")
        if market == "crypto":
            # Yahoo uses BASE-USD symbols. Avoid chained replacements that can
            # accidentally turn BTCUSDT into BTC--USD.
            if ticker.endswith("USDT"):
                ticker = f"{ticker[:-4]}-USD"
            elif ticker.endswith("USD") and not ticker.endswith("-USD"):
                ticker = f"{ticker[:-3]}-USD"
        end_date = end or date.today()
        end_exclusive = end_date + timedelta(days=1)
        start_date = start or (end_exclusive - timedelta(days=365 * 3))
        requested_start = start_date
        lookback_days = self.max_lookback_days.get(interval)
        if lookback_days is not None:
            start_date = max(start_date, end_date - timedelta(days=lookback_days - 1))
        try:
            frame = yf.download(
                ticker, start=start_date.isoformat(), end=end_exclusive.isoformat(),
                interval=interval, auto_adjust=True, actions=False, progress=False,
                threads=False, group_by="column",
            )
        except Exception as exc:  # provider library has several network exception types
            raise ProviderError(f"Yahoo Finance request failed: {exc}") from exc
        if frame is None or frame.empty:
            raise ProviderError(f"Yahoo Finance returned no data for {ticker}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        frame = frame.rename(columns=str.lower)
        if "volume" not in frame.columns:
            frame["volume"] = 0
        frame = normalize_candles(frame[["open", "high", "low", "close", "volume"]])
        # Exclude a still-forming final candle: signals must be based on completed bars.
        now = pd.Timestamp.now(tz="UTC")
        interval_seconds = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}
        if not frame.empty and interval in interval_seconds:
            last_ts = frame.index[-1]
            if interval == "1d" and market == "india":
                local_now = now.tz_convert(ZoneInfo("Asia/Kolkata"))
                last_day = last_ts.tz_convert(ZoneInfo("Asia/Kolkata")).date()
                if last_day == local_now.date() and (local_now.hour, local_now.minute) < (15, 45):
                    frame = frame.iloc[:-1]
            elif interval == "1d" and market == "global":
                local_now = now.tz_convert(ZoneInfo("America/New_York"))
                last_day = last_ts.tz_convert(ZoneInfo("America/New_York")).date()
                if last_day == local_now.date() and (local_now.hour, local_now.minute) < (16, 5):
                    frame = frame.iloc[:-1]
            elif interval != "1d" and last_ts + pd.Timedelta(seconds=interval_seconds[interval]) > now:
                frame = frame.iloc[:-1]
        elif not frame.empty and interval in {"1wk", "1mo"} and market == "global":
            local_now = now.tz_convert(ZoneInfo("America/New_York"))
            last_date = frame.index[-1].tz_convert(ZoneInfo("America/New_York")).date()
            market_close = (16, 5)
            if interval == "1wk":
                last_week_start = last_date - timedelta(days=last_date.weekday())
                current_week_start = local_now.date() - timedelta(days=local_now.weekday())
                week_complete = local_now.weekday() > 4 or (
                    local_now.weekday() == 4 and (local_now.hour, local_now.minute) >= market_close
                )
                if last_week_start == current_week_start and not week_complete:
                    frame = frame.iloc[:-1]
            else:
                month_end = calendar.monthrange(local_now.year, local_now.month)[1]
                month_complete = local_now.day > month_end or (
                    local_now.day == month_end and (local_now.hour, local_now.minute) >= market_close
                )
                if (last_date.year, last_date.month) == (local_now.year, local_now.month) and not month_complete:
                    frame = frame.iloc[:-1]
        if frame.empty:
            raise ProviderError("Yahoo Finance returned only an incomplete candle for this interval")
        frame.attrs["source"] = self.name
        frame.attrs["is_adjusted"] = True
        frame.attrs["freshness"] = "provider-dependent; often delayed or end-of-day"
        frame.attrs["history_truncated"] = bool(frame.attrs.get("history_truncated", False) or start_date > requested_start)
        return frame


class BinanceSpotProvider(MarketDataProvider):
    name = "Binance Spot Public Market Data"
    base_url = "https://data-api.binance.vision"
    allowed_intervals = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_candles(self, symbol: str, *, market: str, exchange: str | None,
                      interval: str, start: date | None, end: date | None) -> pd.DataFrame:
        if market != "crypto":
            raise ProviderError("Binance provider only supports crypto market pairs")
        if interval not in self.allowed_intervals:
            raise ProviderError(f"Unsupported Binance interval: {interval}")
        pair = symbol.upper().replace("-", "")
        if not pair.endswith(("USDT", "BTC", "ETH", "FDUSD", "USDC")):
            pair += "USDT"
        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000) if start else None
        end_ms = (
            int((pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)).timestamp() * 1000) - 1
            if end else None
        )
        # Binance limits each kline response to 1,000 candles. Bound each
        # history request to 2,500 bars (three pages maximum).
        raw: list[list[Any]] = []
        cursor_ms = start_ms
        max_fetch_candles = MAX_HISTORY_CANDLES + 1
        max_pages = (max_fetch_candles + 999) // 1000
        truncated = False
        try:
            for page_number in range(max_pages):
                page_limit = min(1000, max_fetch_candles - len(raw))
                params: dict[str, Any] = {"symbol": pair, "interval": interval, "limit": page_limit}
                if cursor_ms is not None:
                    params["startTime"] = cursor_ms
                if end_ms is not None:
                    params["endTime"] = end_ms
                response = httpx.get(
                    f"{self.base_url}/api/v3/klines", params=params,
                    timeout=self.settings.http_timeout_seconds,
                )
                response.raise_for_status()
                page = response.json()
                if not page:
                    break
                raw.extend(page)
                last_close_ms = int(page[-1][6])
                if len(page) < page_limit or (end_ms is not None and last_close_ms >= end_ms):
                    break
                if len(raw) >= max_fetch_candles:
                    truncated = end_ms is None or last_close_ms < end_ms
                    break
                cursor_ms = last_close_ms + 1
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Binance market-data request failed: {exc}") from exc
        # Some APIs can return the boundary candle twice when paging; deduplicate by open time.
        unique = {int(item[0]): item for item in raw}
        raw = [unique[key] for key in sorted(unique)]
        rows = [
            {"timestamp": pd.to_datetime(item[0], unit="ms", utc=True),
             "open": item[1], "high": item[2], "low": item[3], "close": item[4], "volume": item[5]}
            for item in raw
        ]
        frame = _to_frame(rows, self.name, adjusted=False, max_candles=max_fetch_candles)
        # Binance returns the active candle as the final row. Remove it so every signal is final-bar only.
        now = pd.Timestamp.now(tz="UTC")
        if len(raw):
            last_close_ms = int(raw[-1][6])
            last_close = pd.to_datetime(last_close_ms, unit="ms", utc=True)
            if last_close > now:
                frame = frame.iloc[:-1]
        frame = normalize_candles(frame, max_candles=MAX_HISTORY_CANDLES)
        frame.attrs["source"] = self.name
        frame.attrs["is_adjusted"] = False
        frame.attrs["freshness"] = "exchange public market data"
        frame.attrs["history_truncated"] = bool(frame.attrs.get("history_truncated", False) or truncated)
        frame.attrs["history_pages"] = min(max_pages, (len(raw) + 999) // 1000)
        return frame
