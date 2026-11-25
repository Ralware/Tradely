from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.core.config import Settings
from app.core.instruments import (
    TRADINGVIEW_PROVIDER,
    canonical_instrument,
)
from app.core.models import Instrument, TradingRules
from app.providers.base import get_adjustment_status
from app.core.trading_rules import (
    default_trading_rules,
    tradingview_rules_from_symbol_info,
)

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
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _iso_from_unix(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


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
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
    now = now or datetime.now(UTC)
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
    now = now or datetime.now(UTC)
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
    status = quote.get("adjustment_status")
    if status not in {"adjusted", "unadjusted", "unknown"}:
        # Previously persisted booleans cannot prove the provider's adjustment behavior.
        status = "unknown"
    quote["adjustment_status"] = status
    quote["is_adjusted"] = True if status == "adjusted" else False if status == "unadjusted" else None
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
    exchange = instrument.get("exchange") or ""
    symbol = instrument.get("symbol") or instrument_id.split(":")[-1]
    provider_symbol = instrument.get("provider_symbol") or instrument.get("instrument_provider_symbol")
    if not provider_symbol or ":" not in str(provider_symbol):
        provider_symbol = f"{exchange}:{symbol}" if exchange else symbol
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "name": instrument.get("name") or instrument.get("instrument_name") or symbol,
        "market": instrument.get("market") or instrument_id.split(":")[0],
        "exchange": exchange,
        "currency": instrument.get("currency") or instrument.get("instrument_currency") or "",
        "asset_type": instrument.get("asset_type") or (
            "crypto" if str(instrument.get("market")) == "crypto" else "equity"
        ),
        "provider": instrument.get("provider") or instrument.get("instrument_provider")
        or TRADINGVIEW_PROVIDER,
        "provider_symbol": provider_symbol,
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
    single TradingView batch response is reused and stale responses cannot
    overwrite a newer timestamp.
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def quote_for(self, instrument: Instrument | dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        return self.quotes_for([instrument], force=force)[0]

    def quotes_for(
        self,
        instruments: list[Instrument | dict[str, Any]],
        *,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        seen: set[str] = set()
        for instrument in instruments:
            payload = _instrument_payload(instrument)
            if payload["instrument_id"] in seen:
                continue
            seen.add(payload["instrument_id"])
            payloads.append(payload)

        output: dict[str, dict[str, Any]] = {}
        due: list[dict[str, Any]] = []
        now_monotonic = time.monotonic()
        for payload in payloads:
            instrument_id = payload["instrument_id"]
            with self._lock_for(instrument_id):
                entry = self._cache.get(instrument_id)
                failure = self._failures.get(instrument_id)
                if entry and not force and entry.expires_at > now_monotonic:
                    output[instrument_id] = _present_quote(entry.quote)
                    continue
                if failure and now_monotonic < failure.retry_at and (
                    failure.rate_limited or not force
                ):
                    output[instrument_id] = self._fallback(payload, failure.message)
                    continue
                due.append(payload)

        if due:
            raw_quotes: dict[str, dict[str, Any]] = {}
            errors: dict[str, str] = {}
            batch_error: Exception | None = None
            try:
                raw_quotes, errors = self.market_service.quotes(
                    [payload["provider_symbol"] for payload in due]
                )
            except Exception as exc:  # bridge/network/provider failure
                batch_error = exc
            for payload in due:
                provider_symbol = payload["provider_symbol"]
                raw = raw_quotes.get(provider_symbol)
                error_message = errors.get(provider_symbol)
                if raw is None:
                    message = error_message or (
                        str(batch_error) if batch_error is not None else
                        f"TradingView returned no quote for {provider_symbol}"
                    )
                    exc = QuoteError(message)
                    self._record_failure(payload, exc)
                    output[payload["instrument_id"]] = self._fallback(payload, message)
                    continue
                try:
                    quote = _present_quote(self._quote_from_tradingview(payload, raw))
                except Exception as exc:
                    self._record_failure(payload, exc)
                    output[payload["instrument_id"]] = self._fallback(
                        payload, str(exc) or exc.__class__.__name__
                    )
                    continue
                self._store(payload, quote)
                output[payload["instrument_id"]] = quote

        return [output[payload["instrument_id"]] for payload in payloads]

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
        now = now or datetime.now(UTC)
        if trade_time.tzinfo is None:
            trade_time = trade_time.replace(tzinfo=UTC)
        trade_time = trade_time.astimezone(UTC)
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
        try:
            info = self.market_service.symbol_info(payload["provider_symbol"])
            rules = tradingview_rules_from_symbol_info(info, payload["provider_symbol"])
        except Exception:
            return default_trading_rules(payload)
        with self._lock:
            self._rules[instrument_id] = (
                now_monotonic + max(60, self.settings.market_cache_seconds),
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
        now = now or datetime.now(UTC)
        trade_time = trade_time.astimezone(UTC)
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
                interval=interval, days=days, provider="auto", full_history=False,
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
            "is_adjusted": True if get_adjustment_status(frame) == "adjusted" else False if get_adjustment_status(frame) == "unadjusted" else None,
            "adjustment_status": get_adjustment_status(frame),
            "provider_freshness": frame.attrs.get("freshness"),
            "historical_interval": interval,
            "error": None,
        }

    def invalidate(self, instrument_id: str) -> None:
        with self._lock:
            self._cache.pop(instrument_id, None)

    def shutdown(self) -> None:
        """Kept for the application lifespan; the bridge owns network resources."""

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
        message = str(exc) or exc.__class__.__name__
        with self._lock:
            previous = self._failures.get(instrument_id)
            failures = (previous.failures if previous else 0) + 1
            base = max(1, self.settings.quote_backoff_base_seconds)
            maximum = max(base, self.settings.quote_backoff_max_seconds)
            delay = min(maximum, base * (2 ** min(failures - 1, 8)))
            rate_limited = (
                isinstance(exc, QuoteRateLimited)
                or getattr(exc, "status_code", None) in {418, 429}
                or "rate limit" in message.lower()
            )
            if rate_limited:
                delay = max(delay, 60)
            self._failures[instrument_id] = _FailureState(
                failures=failures,
                retry_at=time.monotonic() + delay,
                message=message,
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
            raw["retrieved_at"] = raw.get("retrieved_at") or _iso(datetime.now(UTC))
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
            "retrieved_at": _iso(datetime.now(UTC)),
            "quote_type": "unavailable",
            "freshness": "unavailable",
            "is_stale": False,
            "age_seconds": None,
            "market_status": market_status_for(payload["market"]),
            "is_adjusted": None,
            "adjustment_status": "unknown",
            "error": error,
        }

    # ------------------------------------------------------------------
    # TradingView bridge response mapping
    # ------------------------------------------------------------------
    def _quote_from_tradingview(
        self, payload: dict[str, Any], raw: dict[str, Any]
    ) -> dict[str, Any]:
        provider_symbol = payload["provider_symbol"]
        price = _as_float(raw.get("lp"))
        if price is None:
            raise QuoteInvalidInstrument(
                f"TradingView did not supply a last price for {provider_symbol}"
            )
        previous_close = _as_float(raw.get("prev_close_price"))
        day_change = _as_float(raw.get("ch"))
        if day_change is None and previous_close is not None:
            day_change = price - previous_close
        day_change_pct = _as_float(raw.get("chp"))
        if day_change_pct is None and day_change is not None and previous_close:
            day_change_pct = (day_change / previous_close) * 100
        delay = _as_float(raw.get("delay")) or 0.0
        update_mode = str(raw.get("update_mode") or "")
        delayed = delay > 0 or "delay" in update_mode.lower()
        currency = str(
            raw.get("currency_code") or payload.get("currency") or ""
        ).strip().upper() or None
        quote_time = _iso_from_unix(raw.get("lp_time"))
        return {
            **payload,
            "provider": TRADINGVIEW_PROVIDER,
            "price": price,
            "previous_close": previous_close,
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "day_high": _as_float(raw.get("high_price")),
            "day_low": _as_float(raw.get("low_price")),
            "volume": _as_float(raw.get("volume")),
            "quote_time": quote_time,
            "retrieved_at": _iso(datetime.now(UTC)),
            "quote_type": "delayed" if delayed else "real_time",
            "transport": "bridge",
            "is_adjusted": None,
            "adjustment_status": "unknown",
            "currency": currency,
            "delay_seconds": delay,
            "update_mode": update_mode or None,
            "provider_freshness": (
                f"TradingView update_mode={update_mode or 'unknown'}; "
                f"delay={int(delay)}s"
            ),
            "error": None,
        }
