from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from pydantic import BaseModel

from app.core.config import Settings
from app.core.instruments import canonical_instrument
from app.core.models import Instrument, TradingRules
from app.core.trading_rules import binance_rules_from_exchange_info, default_trading_rules

CRYPTO_PROVIDER = "Binance Spot Public Market Data"
CRYPTO_STALE_SECONDS = 300
CRYPTO_LIVE_SECONDS = 60
EQUITY_STALE_HOURS = 168
HISTORICAL_QUOTE_AFTER = timedelta(minutes=10)
_EQUITY_SESSIONS = {
    "india": (ZoneInfo("Asia/Kolkata"), 15 * 60 + 30),
    "global": (ZoneInfo("America/New_York"), 16 * 60),
}


class QuoteError(RuntimeError):
    """A provider quote could not be obtained."""


class QuoteRateLimited(QuoteError):
    """The provider asked us to slow down."""


class QuoteInvalidInstrument(QuoteError):
    """The exact instrument is not supported by the provider."""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def market_status_for(market: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if market == "crypto":
        return "24/7"
    if market == "india":
        zone = ZoneInfo("Asia/Kolkata")
        local = now.astimezone(zone)
        if local.weekday() >= 5:
            return "closed"
        minutes = local.hour * 60 + local.minute
        return "open" if 9 * 60 + 15 <= minutes <= 15 * 60 + 30 else "closed"
    zone = ZoneInfo("America/New_York")
    local = now.astimezone(zone)
    if local.weekday() >= 5:
        return "closed"
    minutes = local.hour * 60 + local.minute
    return "open" if 9 * 60 + 30 <= minutes <= 16 * 60 else "closed"


def _present_quote(raw: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Recompute age, freshness and market status without inventing prices."""
    now = now or datetime.now(timezone.utc)
    quote = dict(raw)
    quote_type = quote.get("quote_type") or "unavailable"
    price = _as_float(quote.get("price"))
    quote_time = _parse_time(quote.get("quote_time"))
    age_seconds = (now - quote_time).total_seconds() if quote_time else None

    if price is None:
        freshness = "unavailable"
        quote_type = "unavailable"
    elif quote_type == "real_time":
        if age_seconds is None or age_seconds > CRYPTO_STALE_SECONDS:
            freshness = "stale"
            quote_type = "stale"
        elif age_seconds <= CRYPTO_LIVE_SECONDS:
            freshness = "live"
        else:
            freshness = "delayed"
            quote_type = "delayed"
    elif quote_type == "historical":
        freshness = "historical"
    elif quote_type in {"end_of_day", "last_available", "delayed", "previous_close"}:
        max_age = EQUITY_STALE_HOURS * 3600
        if age_seconds is not None and age_seconds > max_age:
            freshness = "stale"
            quote_type = "stale"
        elif quote_type == "end_of_day":
            freshness = "eod"
        else:
            freshness = "delayed"
    elif quote_type in {"cached", "stale"}:
        max_age = CRYPTO_STALE_SECONDS if quote.get("market") == "crypto" else EQUITY_STALE_HOURS * 3600
        if age_seconds is not None and age_seconds > max_age:
            freshness = "stale"
            quote_type = "stale"
        else:
            freshness = "cached"
            quote_type = "cached"
    else:
        freshness = "unavailable"
        quote_type = "unavailable"

    quote.update({
        "price": price,
        "quote_type": quote_type,
        "freshness": freshness,
        "is_stale": freshness == "stale",
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "market_status": market_status_for(str(quote.get("market") or ""), now),
        "retrieved_at": quote.get("retrieved_at") or _iso(now),
    })
    return quote


def _instrument_payload(instrument: Instrument | dict[str, Any]) -> dict[str, Any]:
    if isinstance(instrument, BaseModel):
        return instrument.model_dump()
    instrument_id = instrument.get("instrument_id") or ""
    if not instrument_id:
        resolved = canonical_instrument(
            instrument.get("symbol", ""), instrument.get("market", "india"),
            exchange=instrument.get("exchange"), name=instrument.get("instrument_name"),
            currency=instrument.get("currency"), provider=instrument.get("provider"),
            provider_symbol=instrument.get("provider_symbol"),
        )
        return resolved.model_dump()
    return {
        "instrument_id": instrument_id,
        "symbol": instrument.get("symbol") or instrument_id.split(":")[-1],
        "name": instrument.get("name") or instrument.get("instrument_name") or instrument.get("symbol") or "",
        "market": instrument.get("market") or instrument_id.split(":")[0],
        "exchange": instrument.get("exchange") or "",
        "currency": instrument.get("currency") or instrument.get("instrument_currency") or "",
        "asset_type": instrument.get("asset_type") or (
            "crypto" if str(instrument.get("market")) == "crypto" else "equity"
        ),
        "provider": instrument.get("provider") or instrument.get("instrument_provider") or "",
        "provider_symbol": instrument.get("provider_symbol") or instrument.get("instrument_provider_symbol")
        or instrument.get("symbol") or "",
    }


@dataclass
class _CacheEntry:
    quote: dict[str, Any]
    expires_at: float


@dataclass
class _FailureState:
    failures: int
    retry_at: float
    message: str
    rate_limited: bool


class QuoteService:
    """Centralised quote cache, refresh policy and provider failure handling.

    All portfolio, watchlist and analysis quotes pass through this service so a
    single provider response is reused and stale responses cannot overwrite a
    newer timestamp.
    """

    def __init__(self, settings: Settings, market_service: Any, db: Any):
        self.settings = settings
        self.market_service = market_service
        self.db = db
        self._cache: dict[str, _CacheEntry] = {}
        self._failures: dict[str, _FailureState] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._rules: dict[str, tuple[float, TradingRules]] = {}
        self._lock = threading.RLock()
        self._stream_tokens: dict[str, dict[str, dict[str, Any]]] = {}
        self._stream = BinanceStreamManager(self, settings)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def quote_for(self, instrument: Instrument | dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        payload = _instrument_payload(instrument)
        instrument_id = payload["instrument_id"]
        lock = self._lock_for(instrument_id)
        with lock:
            now_monotonic = time.monotonic()
            entry = self._cache.get(instrument_id)
            failure = self._failures.get(instrument_id)

            if entry and not force and entry.expires_at > now_monotonic:
                return _present_quote(entry.quote)
            if failure and now_monotonic < failure.retry_at and (failure.rate_limited or not force):
                return self._fallback(payload, failure.message)

            try:
                raw = self._fetch_quote(payload)
            except Exception as exc:  # provider/library/network errors
                message = str(exc) or exc.__class__.__name__
                self._record_failure(payload, exc)
                return self._fallback(payload, message)
            quote = _present_quote(raw)
            self._store(payload, quote)
            return quote

    def quotes_for(
        self,
        instruments: list[Instrument | dict[str, Any]],
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for instrument in instruments:
            payload = _instrument_payload(instrument)
            if payload["instrument_id"] in seen:
                continue
            seen.add(payload["instrument_id"])
            output.append(self.quote_for(payload, force=force))
        return output

    def quote_for_transaction(
        self,
        instrument: Instrument | dict[str, Any],
        trade_time: datetime,
        *,
        now: datetime | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        """Acquire the quote that may be used for a transaction.

        Recent entries use a freshly refreshed provider quote. Previews pass
        ``force=False`` so typing in the amount field does not bypass the
        provider TTL cache; recording a transaction always forces a refresh.
        Backdated entries use provider history and are explicitly marked
        ``historical``; the current quote is never substituted for a historical
        transaction.
        """
        now = now or datetime.now(timezone.utc)
        if trade_time.tzinfo is None:
            trade_time = trade_time.replace(tzinfo=timezone.utc)
        trade_time = trade_time.astimezone(timezone.utc)
        if trade_time > now + timedelta(minutes=1):
            raise QuoteError("Transaction time cannot be in the future")
        if now - trade_time <= HISTORICAL_QUOTE_AFTER:
            return self.quote_for(instrument, force=force)
        return self.historical_quote_for(instrument, trade_time, now=now)

    def trading_rules_for(self, instrument: Instrument | dict[str, Any]) -> TradingRules:
        """Return the instrument quantity/notional rules used for derivation."""
        payload = _instrument_payload(instrument)
        if payload["market"] != "crypto":
            return default_trading_rules(payload)
        instrument_id = payload["instrument_id"]
        now_monotonic = time.monotonic()
        with self._lock:
            cached = self._rules.get(instrument_id)
            if cached and cached[0] > now_monotonic:
                return cached[1]
        base_url = getattr(self.market_service.binance, "base_url", "https://data-api.binance.vision")
        try:
            response = httpx.get(
                f"{base_url}/api/v3/exchangeInfo",
                params={"symbol": payload["provider_symbol"]},
                timeout=self.settings.http_timeout_seconds,
            )
            if response.status_code >= 400:
                raise QuoteError(f"Binance exchange rules returned HTTP {response.status_code}")
            data = response.json()
            if not isinstance(data, dict):
                raise QuoteError("Binance exchange rules returned an unexpected payload")
            rules = binance_rules_from_exchange_info(data, payload["provider_symbol"])
        except Exception:
            return default_trading_rules(payload)
        with self._lock:
            self._rules[instrument_id] = (
                now_monotonic + max(60, self.settings.quote_rules_ttl_seconds),
                rules,
            )
        return rules

    def historical_quote_for(
        self,
        instrument: Instrument | dict[str, Any],
        trade_time: datetime,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fetch a provider price at or before a backdated transaction time."""
        payload = _instrument_payload(instrument)
        now = now or datetime.now(timezone.utc)
        trade_time = trade_time.astimezone(timezone.utc)
        age = now - trade_time
        market = payload["market"]
        interval = "1d"
        if market == "crypto":
            if age <= timedelta(days=7):
                interval = "1m"
            elif age <= timedelta(days=180):
                interval = "1h"
        days = max(2, min(3650, age.days + 3))
        try:
            frame, source = self.market_service.candles(
                payload["symbol"], market=market, exchange=payload["exchange"],
                interval=interval, days=days, provider="auto",
            )
        except Exception as exc:
            raise QuoteError(f"Historical price unavailable: {exc}") from exc
        if frame is None or frame.empty:
            raise QuoteError("Historical price unavailable: provider returned no candles")

        eligible = frame
        if interval == "1d" and market in _EQUITY_SESSIONS:
            zone, close_minute = _EQUITY_SESSIONS[market]
            local_at = trade_time.astimezone(zone)
            candle_dates = frame.index.tz_convert(zone)
            local_minutes = local_at.hour * 60 + local_at.minute
            if local_minutes < close_minute:
                eligible = frame[candle_dates.date < local_at.date()]
            else:
                eligible = frame[candle_dates.date <= local_at.date()]
        else:
            eligible = frame[frame.index <= trade_time]

        if eligible.empty:
            raise QuoteError(
                "Historical price unavailable for the selected transaction time; "
                "the current price will not be substituted"
            )
        row = eligible.iloc[-1]
        previous = eligible.iloc[-2] if len(eligible) > 1 else None
        price = _as_float(row.get("close"))
        if price is None:
            raise QuoteError("Historical provider row has no usable close")
        previous_close = _as_float(previous.get("close")) if previous is not None else None
        change = price - previous_close if previous_close is not None else None
        change_pct = (change / previous_close * 100) if change is not None and previous_close else None
        return {
            **payload,
            "provider": source,
            "price": price,
            "previous_close": previous_close,
            "day_change": change,
            "day_change_pct": change_pct,
            "day_high": _as_float(row.get("high")),
            "day_low": _as_float(row.get("low")),
            "volume": _as_float(row.get("volume")),
            "quote_time": _iso(eligible.index[-1].to_pydatetime()),
            "retrieved_at": _iso(now),
            "quote_type": "historical",
            "freshness": "historical",
            "is_stale": False,
            "age_seconds": round(age.total_seconds(), 3),
            "market_status": market_status_for(market, now),
            "transport": "historical",
            "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
            "provider_freshness": frame.attrs.get("freshness"),
            "historical_interval": interval,
            "error": None,
        }

    def apply_stream_tick(self, instrument: Instrument | dict[str, Any], tick: dict[str, Any]) -> dict[str, Any] | None:
        payload = _instrument_payload(instrument)
        raw = {
            **payload,
            "provider": tick.get("provider") or payload.get("provider") or CRYPTO_PROVIDER,
            "price": tick.get("price"),
            "previous_close": tick.get("previous_close"),
            "day_change": tick.get("day_change"),
            "day_change_pct": tick.get("day_change_pct"),
            "day_high": tick.get("day_high"),
            "day_low": tick.get("day_low"),
            "volume": tick.get("volume"),
            "quote_time": tick.get("quote_time"),
            "retrieved_at": _iso(datetime.now(timezone.utc)),
            "quote_type": "real_time",
            "transport": "websocket",
            "is_adjusted": False,
            "error": None,
        }
        with self._lock:
            entry = self._cache.get(payload["instrument_id"])
            if entry:
                old_time = _parse_time(entry.quote.get("quote_time"))
                new_time = _parse_time(raw.get("quote_time"))
                if old_time and new_time and new_time < old_time:
                    return None
        quote = _present_quote(raw)
        self._store(payload, quote, ttl_seconds=self._ttl(payload["market"]))
        return quote

    def invalidate(self, instrument_id: str) -> None:
        with self._lock:
            self._cache.pop(instrument_id, None)

    def subscribe_stream(self, instruments: list[Instrument | dict[str, Any]]) -> str:
        token = uuid.uuid4().hex
        payloads = {item["instrument_id"]: item for item in map(_instrument_payload, instruments)}
        with self._lock:
            self._stream_tokens[token] = payloads
            all_instruments = {
                key: value for items in self._stream_tokens.values() for key, value in items.items()
            }
        try:
            self._stream.update(all_instruments)
        except RuntimeError:
            # No running event loop (for example in a synchronous unit test).
            pass
        return token

    def unsubscribe_stream(self, token: str) -> None:
        with self._lock:
            self._stream_tokens.pop(token, None)
            all_instruments = {
                key: value for items in self._stream_tokens.values() for key, value in items.items()
            }
        try:
            self._stream.update(all_instruments)
        except RuntimeError:
            pass
        if not all_instruments:
            self._stream.stop()

    def shutdown(self) -> None:
        self._stream.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _lock_for(self, instrument_id: str) -> threading.Lock:
        with self._lock:
            if instrument_id not in self._locks:
                self._locks[instrument_id] = threading.Lock()
            return self._locks[instrument_id]

    def _ttl(self, market: str) -> int:
        if market == "crypto":
            return self.settings.quote_crypto_ttl_seconds
        if market == "india":
            return self.settings.quote_india_ttl_seconds
        return self.settings.quote_global_ttl_seconds

    def _store(
        self,
        payload: dict[str, Any],
        quote: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl(payload["market"])
        with self._lock:
            existing = self._cache.get(payload["instrument_id"])
            if existing:
                old_time = _parse_time(existing.quote.get("quote_time"))
                new_time = _parse_time(quote.get("quote_time"))
                if old_time and new_time and new_time < old_time:
                    return
            self._cache[payload["instrument_id"]] = _CacheEntry(
                quote=quote, expires_at=time.monotonic() + max(1, ttl)
            )
            self._failures.pop(payload["instrument_id"], None)
        try:
            self.db.save_quote_snapshot(payload["instrument_id"], quote)
        except Exception:
            # Persisting a last-known quote must never break the portfolio.
            pass

    def _record_failure(self, payload: dict[str, Any], exc: Exception) -> None:
        instrument_id = payload["instrument_id"]
        with self._lock:
            previous = self._failures.get(instrument_id)
            failures = (previous.failures if previous else 0) + 1
            base = max(1, self.settings.quote_backoff_base_seconds)
            maximum = max(base, self.settings.quote_backoff_max_seconds)
            delay = min(maximum, base * (2 ** min(failures - 1, 8)))
            rate_limited = isinstance(exc, QuoteRateLimited) or getattr(exc, "status_code", None) in {418, 429}
            if rate_limited:
                delay = max(delay, 60)
            self._failures[instrument_id] = _FailureState(
                failures=failures,
                retry_at=time.monotonic() + delay,
                message=str(exc) or exc.__class__.__name__,
                rate_limited=rate_limited,
            )

    def _fallback(self, payload: dict[str, Any], error: str) -> dict[str, Any]:
        raw: dict[str, Any] | None = None
        with self._lock:
            entry = self._cache.get(payload["instrument_id"])
            if entry:
                raw = dict(entry.quote)
        if raw is None:
            try:
                raw = self.db.get_quote_snapshot(payload["instrument_id"])
            except Exception:
                raw = None
        if raw and raw.get("price") is not None:
            raw = dict(raw)
            raw["quote_type"] = "cached"
            raw["retrieved_at"] = raw.get("retrieved_at") or _iso(datetime.now(timezone.utc))
            raw["error"] = error
            quote = _present_quote(raw)
            if quote["freshness"] not in {"stale", "unavailable"}:
                quote["quote_type"] = "cached"
            return quote
        return {
            **payload,
            "price": None,
            "previous_close": None,
            "day_change": None,
            "day_change_pct": None,
            "day_high": None,
            "day_low": None,
            "volume": None,
            "quote_time": None,
            "retrieved_at": _iso(datetime.now(timezone.utc)),
            "quote_type": "unavailable",
            "freshness": "unavailable",
            "is_stale": False,
            "age_seconds": None,
            "market_status": market_status_for(payload["market"]),
            "is_adjusted": None,
            "error": error,
        }

    # ------------------------------------------------------------------
    # Provider fetches
    # ------------------------------------------------------------------
    def _fetch_quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["market"] == "crypto":
            return self._fetch_binance_rest(payload)
        return self._fetch_candle_quote(payload)

    def _fetch_binance_rest(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = payload["provider_symbol"]
        base_url = getattr(self.market_service.binance, "base_url", "https://data-api.binance.vision")
        try:
            response = httpx.get(
                f"{base_url}/api/v3/ticker/24hr",
                params={"symbol": symbol},
                timeout=self.settings.http_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise QuoteError(f"Binance quote request failed: {exc}") from exc
        if response.status_code in {418, 429}:
            raise QuoteRateLimited("Binance rate limit reached")
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("msg") or "")
            except Exception:
                detail = response.text[:120] if getattr(response, "text", None) else ""
            raise QuoteInvalidInstrument(
                f"Binance rejected symbol {symbol}: {detail or f'HTTP {response.status_code}'}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise QuoteError("Binance returned an unreadable quote") from exc
        if not isinstance(data, dict):
            raise QuoteError("Binance returned an unexpected quote payload")
        price = _as_float(data.get("lastPrice"))
        if price is None:
            raise QuoteError(f"Binance did not supply a last price for {symbol}")
        open_price = _as_float(data.get("openPrice"))
        change = _as_float(data.get("priceChange"))
        if change is None and open_price is not None:
            change = price - open_price
        change_pct = _as_float(data.get("priceChangePercent"))
        if change_pct is None and change is not None and open_price:
            change_pct = (change / open_price) * 100
        close_ms = data.get("closeTime")
        quote_time = None
        if close_ms is not None:
            try:
                quote_time = _iso(datetime.fromtimestamp(float(close_ms) / 1000, tz=timezone.utc))
            except (TypeError, ValueError, OSError):
                quote_time = None
        return {
            **payload,
            "provider": CRYPTO_PROVIDER,
            "price": price,
            "previous_close": open_price,
            "day_change": change,
            "day_change_pct": change_pct,
            "day_high": _as_float(data.get("highPrice")),
            "day_low": _as_float(data.get("lowPrice")),
            "volume": _as_float(data.get("volume")),
            "quote_time": quote_time or _iso(datetime.now(timezone.utc)),
            "retrieved_at": _iso(datetime.now(timezone.utc)),
            "quote_type": "real_time",
            "transport": "rest",
            "is_adjusted": False,
            "error": None,
        }

    def _fetch_candle_quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            frame, source = self.market_service.candles(
                payload["symbol"], market=payload["market"], exchange=payload["exchange"],
                interval="1d", days=10, provider="auto",
            )
        except Exception as exc:
            raise QuoteError(str(exc)) from exc
        if frame is None or frame.empty:
            raise QuoteError("The market-data provider returned no completed daily price")
        latest = frame.iloc[-1]
        previous = frame.iloc[-2] if len(frame) > 1 else None
        price = _as_float(latest.get("close"))
        if price is None:
            raise QuoteError("The latest daily candle has no usable close")
        previous_close = _as_float(previous.get("close")) if previous is not None else None
        change = price - previous_close if previous_close is not None else None
        change_pct = (change / previous_close * 100) if change is not None and previous_close else None
        quote_type = "end_of_day" if payload["market"] == "india" else "last_available"
        quote_time = _iso(frame.index[-1].to_pydatetime())
        return {
            **payload,
            "provider": source,
            "price": price,
            "previous_close": previous_close,
            "day_change": change,
            "day_change_pct": change_pct,
            "day_high": _as_float(latest.get("high")),
            "day_low": _as_float(latest.get("low")),
            "volume": _as_float(latest.get("volume")),
            "quote_time": quote_time,
            "retrieved_at": _iso(datetime.now(timezone.utc)),
            "quote_type": quote_type,
            "transport": "rest",
            "is_adjusted": bool(frame.attrs.get("is_adjusted", False)),
            "provider_freshness": frame.attrs.get("freshness"),
            "error": None,
        }


class BinanceStreamManager:
    """One shared Binance public ticker stream for every held/watchlist pair."""

    def __init__(self, service: QuoteService, settings: Settings):
        self.service = service
        self.settings = settings
        self._instruments: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.RLock()

    @staticmethod
    def stream_url(symbols: list[str]) -> str:
        streams = "/".join(f"{symbol.lower()}@ticker" for symbol in sorted(symbols))
        return f"wss://data-stream.binance.vision/stream?streams={streams}"

    @staticmethod
    def parse_message(message: str | bytes) -> tuple[str, dict[str, Any]] | None:
        import json

        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        stream = payload.get("stream") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None
        symbol = str(data.get("s") or "").upper()
        if not symbol:
            return None
        return symbol, data

    @staticmethod
    def tick_from_payload(data: dict[str, Any]) -> dict[str, Any]:
        price = _as_float(data.get("c"))
        open_price = _as_float(data.get("o"))
        change = _as_float(data.get("p"))
        change_pct = _as_float(data.get("P"))
        event_ms = data.get("E")
        quote_time = None
        if event_ms is not None:
            try:
                quote_time = _iso(datetime.fromtimestamp(float(event_ms) / 1000, tz=timezone.utc))
            except (TypeError, ValueError, OSError):
                quote_time = None
        return {
            "price": price,
            "previous_close": open_price,
            "day_change": change if change is not None else (price - open_price if price and open_price else None),
            "day_change_pct": change_pct,
            "day_high": _as_float(data.get("h")),
            "day_low": _as_float(data.get("l")),
            "volume": _as_float(data.get("v")),
            "quote_time": quote_time,
            "provider": CRYPTO_PROVIDER,
        }

    def update(self, instruments: dict[str, dict[str, Any]]) -> None:
        crypto = {
            key: value for key, value in instruments.items() if value.get("market") == "crypto"
        }
        with self._lock:
            changed = set(crypto) != set(self._instruments)
            self._instruments = crypto
        if not crypto:
            self.stop()
            return
        if not self.settings.binance_stream_enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if changed or self._task is None or self._task.done() or self._loop is not loop:
            self._loop = loop
            if self._task and not self._task.done():
                self._task.cancel()
            self._task = loop.create_task(self._run())

    def stop(self) -> None:
        with self._lock:
            task = self._task
            self._task = None
            self._instruments = {}
        if task and not task.done():
            task.cancel()

    async def _run(self) -> None:
        import websockets

        failures = 0
        while True:
            with self._lock:
                instruments = dict(self._instruments)
            if not instruments:
                return
            symbols = sorted(
                {value.get("provider_symbol") or value.get("symbol") for value in instruments.values()}
            )
            url = self.stream_url([symbol for symbol in symbols if symbol])
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5) as socket:
                    failures = 0
                    while True:
                        with self._lock:
                            current_symbols = {
                                value.get("provider_symbol") or value.get("symbol")
                                for value in self._instruments.values()
                            }
                        if set(symbols) != {symbol for symbol in current_symbols if symbol}:
                            break
                        try:
                            message = await asyncio.wait_for(socket.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        parsed = self.parse_message(message)
                        if not parsed:
                            continue
                        symbol, data = parsed
                        instrument = next(
                            (
                                value for value in instruments.values()
                                if str(value.get("provider_symbol") or value.get("symbol")).upper() == symbol
                            ),
                            None,
                        )
                        if instrument:
                            self.service.apply_stream_tick(
                                instrument, self.tick_from_payload(data)
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                delay = min(60, 2 ** min(failures, 6))
                await asyncio.sleep(delay)
