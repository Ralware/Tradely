from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest

from app.core.config import Settings
from app.services.quotes import (
    BinanceStreamManager,
    QuoteInvalidInstrument,
    QuoteRateLimited,
    QuoteService,
    QuoteError,
    _present_quote,
    market_status_for,
)

NOW = datetime.now(timezone.utc).replace(microsecond=0)

CRYPTO = {
    "instrument_id": "crypto:BINANCE:BTCUSDT",
    "symbol": "BTCUSDT",
    "name": "BTCUSDT",
    "market": "crypto",
    "exchange": "BINANCE",
    "currency": "USDT",
    "asset_type": "crypto",
    "provider": "Binance Spot Public Market Data",
    "provider_symbol": "BTCUSDT",
}

INDIA = {
    "instrument_id": "india:NSE:RELIANCE",
    "symbol": "RELIANCE",
    "name": "RELIANCE",
    "market": "india",
    "exchange": "NSE",
    "currency": "INR",
    "asset_type": "equity",
    "provider": "TejHQ",
    "provider_symbol": "RELIANCE",
}


class FakeDb:
    def __init__(self):
        self.snapshots: dict[str, dict] = {}

    def save_quote_snapshot(self, instrument_id, quote):
        self.snapshots[instrument_id] = dict(quote)

    def get_quote_snapshot(self, instrument_id):
        snapshot = self.snapshots.get(instrument_id)
        return dict(snapshot) if snapshot else None


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeMarket:
    def __init__(self, frame=None, error=None):
        self.frame = frame
        self.error = error
        self.binance = SimpleNamespace(base_url="https://example.test")
        self.calls = 0

    def candles(self, symbol, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.frame, "Fake EOD Provider"


def build_service(*, market=None, db=None, **overrides):
    settings = Settings(
        binance_stream_enabled=False,
        quote_crypto_ttl_seconds=10,
        quote_global_ttl_seconds=300,
        quote_india_ttl_seconds=600,
        quote_backoff_base_seconds=5,
        quote_backoff_max_seconds=300,
        http_timeout_seconds=1,
        **overrides,
    )
    return QuoteService(settings, market or FakeMarket(), db or FakeDb())


def binance_payload(price=100.5):
    return {
        "lastPrice": str(price),
        "openPrice": "95",
        "priceChange": "5.5",
        "priceChangePercent": "5.789",
        "highPrice": "102",
        "lowPrice": "94",
        "volume": "1234",
        "closeTime": int(NOW.timestamp() * 1000),
    }


def candle_frame(price=2500.0, previous=2450.0, adjusted=True):
    index = pd.DatetimeIndex([NOW - timedelta(days=1), NOW], tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [previous, price],
            "high": [previous + 10, price + 10],
            "low": [previous - 10, price - 10],
            "close": [previous, price],
            "volume": [1000, 1200],
        },
        index=index,
    )
    frame.attrs["is_adjusted"] = adjusted
    frame.attrs["freshness"] = "provider-dependent"
    return frame


def test_crypto_quote_success_and_ttl_deduplicates_calls(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(200, binance_payload())

    monkeypatch.setattr("app.services.quotes.httpx.get", fake_get)
    service = build_service()

    first = service.quote_for(CRYPTO)
    second = service.quote_for(CRYPTO)

    assert first["price"] == 100.5
    assert first["quote_type"] == "real_time"
    assert first["freshness"] == "delayed" or first["freshness"] == "live"
    assert second["price"] == 100.5
    assert len(calls) == 1


def test_quotes_for_deduplicates_instrument_identity(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(200, binance_payload())

    monkeypatch.setattr("app.services.quotes.httpx.get", fake_get)
    service = build_service()
    quotes = service.quotes_for([CRYPTO, dict(CRYPTO), CRYPTO])
    assert len(quotes) == 1
    assert len(calls) == 1


def test_provider_failure_returns_unavailable_without_losing_cached_snapshot(monkeypatch):
    def failing_get(url, params=None, timeout=None):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.services.quotes.httpx.get", failing_get)
    service = build_service()
    service.db.snapshots[CRYPTO["instrument_id"]] = {
        **CRYPTO,
        "price": 99.0,
        "quote_type": "real_time",
        "quote_time": NOW.isoformat(),
        "retrieved_at": NOW.isoformat(),
    }

    quote = service.quote_for(CRYPTO)
    assert quote["price"] == 99.0
    assert quote["quote_type"] == "cached"
    assert quote["error"]
    assert quote["freshness"] in {"cached", "live", "delayed", "stale"}


def test_failed_provider_is_not_retried_during_backoff(monkeypatch):
    calls = []

    def failing_get(url, params=None, timeout=None):
        calls.append(1)
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.services.quotes.httpx.get", failing_get)
    service = build_service()

    first = service.quote_for(CRYPTO)
    second = service.quote_for(CRYPTO)

    assert first["price"] is None
    assert second["price"] is None
    assert len(calls) == 1
    assert service._failures[CRYPTO["instrument_id"]].failures == 1


def test_rate_limit_uses_extended_backoff(monkeypatch):
    def rate_limited(url, params=None, timeout=None):
        return FakeResponse(429, {"msg": "Too many requests"})

    monkeypatch.setattr("app.services.quotes.httpx.get", rate_limited)
    service = build_service()
    quote = service.quote_for(CRYPTO)
    assert quote["price"] is None
    state = service._failures[CRYPTO["instrument_id"]]
    assert state.rate_limited is True
    assert state.message


def test_invalid_crypto_symbol_reports_provider_rejection(monkeypatch):
    def rejected(url, params=None, timeout=None):
        return FakeResponse(400, {"msg": "Invalid symbol."})

    monkeypatch.setattr("app.services.quotes.httpx.get", rejected)
    service = build_service()
    quote = service.quote_for(CRYPTO)
    assert quote["price"] is None
    assert "BTCUSDT" in quote["error"]


def test_indian_equity_quote_is_end_of_day_never_real_time():
    service = build_service(market=FakeMarket(candle_frame()))
    quote = service.quote_for(INDIA)
    assert quote["price"] == 2500.0
    assert quote["quote_type"] == "end_of_day"
    assert quote["previous_close"] == 2450.0
    assert quote["day_change"] == 50.0
    assert quote["is_adjusted"] is True


def test_international_equity_quote_is_last_available():
    instrument = {
        **INDIA,
        "instrument_id": "global:NASDAQ:AAPL",
        "symbol": "AAPL",
        "market": "global",
        "exchange": "NASDAQ",
        "currency": "USD",
        "provider": "Yahoo Finance (yfinance; unofficial)",
    }
    service = build_service(market=FakeMarket(candle_frame(price=190, previous=188)))
    quote = service.quote_for(instrument)
    assert quote["quote_type"] == "last_available"
    assert quote["freshness"] == "delayed"


def test_stale_live_quote_is_downgraded_to_stale():
    stale = _present_quote(
        {
            **CRYPTO,
            "price": 100,
            "quote_type": "real_time",
            "quote_time": (NOW - timedelta(minutes=10)).isoformat(),
        },
        now=NOW,
    )
    assert stale["freshness"] == "stale"
    assert stale["is_stale"] is True
    assert stale["quote_type"] == "stale"


def test_newer_stream_tick_is_not_overwritten_by_older_tick():
    service = build_service()
    newer = {
        "price": 101,
        "quote_time": (NOW + timedelta(seconds=10)).isoformat(),
        "previous_close": 95,
        "day_change": 6,
        "day_change_pct": 6.3,
    }
    older = {
        "price": 99,
        "quote_time": (NOW - timedelta(seconds=10)).isoformat(),
        "previous_close": 95,
        "day_change": 4,
        "day_change_pct": 4.2,
    }
    assert service.apply_stream_tick(CRYPTO, newer)["price"] == 101
    assert service.apply_stream_tick(CRYPTO, older) is None
    assert service.quote_for(CRYPTO)["price"] == 101


def test_binance_stream_message_parsing_and_tick_normalisation():
    parsed = BinanceStreamManager.parse_message(
        '{"stream":"btcusdt@ticker","data":{"s":"BTCUSDT","c":"101.5","o":"95",'
        '"p":"6.5","P":"6.8","h":"103","l":"94","v":"10","E":1760000000000}}'
    )
    assert parsed is not None
    symbol, data = parsed
    assert symbol == "BTCUSDT"
    tick = BinanceStreamManager.tick_from_payload(data)
    assert tick["price"] == 101.5
    assert tick["day_change"] == 6.5
    assert tick["quote_time"].endswith("+00:00")


def test_stream_manager_uses_one_stream_url_for_all_pairs():
    url = BinanceStreamManager.stream_url(["BTCUSDT", "ETHUSDT"])
    assert url == "wss://data-stream.binance.vision/stream?streams=btcusdt@ticker/ethusdt@ticker"


def test_market_status_distinguishes_sessions():
    assert market_status_for("crypto", NOW) == "24/7"
    india_open = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    india_closed = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)  # 19:30 IST
    assert market_status_for("india", india_open) == "open"
    assert market_status_for("india", india_closed) == "closed"


def test_historical_transaction_quote_uses_provider_history_not_current_price():
    index = pd.DatetimeIndex([NOW - timedelta(days=2), NOW - timedelta(days=1)], tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [95, 195],
            "high": [105, 205],
            "low": [94, 194],
            "close": [100, 200],
            "volume": [1000, 1200],
        },
        index=index,
    )
    frame.attrs["is_adjusted"] = True
    service = build_service(market=FakeMarket(frame))
    trade_time = (NOW - timedelta(days=1)).replace(hour=12)
    quote = service.quote_for_transaction(INDIA, trade_time, now=NOW)
    assert quote["price"] == 200
    assert quote["quote_type"] == "historical"
    assert quote["freshness"] == "historical"
    assert quote["quote_time"] is not None


def test_historical_intraday_equity_does_not_use_same_day_close_before_session_end():
    index = pd.DatetimeIndex([NOW - timedelta(days=2), NOW - timedelta(days=1)], tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [95, 195],
            "high": [105, 205],
            "low": [94, 194],
            "close": [100, 200],
            "volume": [1000, 1200],
        },
        index=index,
    )
    frame.attrs["is_adjusted"] = True
    service = build_service(market=FakeMarket(frame))
    # 10:30 IST, before the Indian cash close, so the same-day close is not yet
    # knowable. The provider's previous completed close must be used.
    trade_time = (NOW - timedelta(days=1)).replace(hour=5)
    quote = service.quote_for_transaction(INDIA, trade_time, now=NOW)
    assert quote["price"] == 100
    assert quote["quote_type"] == "historical"


def test_recent_transaction_quote_uses_live_quote_path():
    service = build_service(market=FakeMarket(candle_frame(price=2500.0)))
    quote = service.quote_for_transaction(INDIA, NOW - timedelta(minutes=1), now=NOW)
    assert quote["price"] == 2500.0
    assert quote["quote_type"] == "end_of_day"


def test_binance_trading_rules_use_exchange_info(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert params == {"symbol": "BTCUSDT"}
        return FakeResponse(200, {"symbols": [{
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.00001000",
                 "minQty": "0.00001000", "maxQty": "9000"},
                {"filterType": "NOTIONAL", "minNotional": "5"},
            ],
        }]})

    monkeypatch.setattr("app.services.quotes.httpx.get", fake_get)
    service = build_service()
    rules = service.trading_rules_for(CRYPTO)
    assert rules.quantity_step == 0.00001
    assert rules.min_notional == 5
    assert rules.is_fallback is False


def test_binance_trading_rules_fallback_is_explicit(monkeypatch):
    def failing_get(url, params=None, timeout=None):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("app.services.quotes.httpx.get", failing_get)
    service = build_service()
    rules = service.trading_rules_for(CRYPTO)
    assert rules.is_fallback is True
    assert "Fallback" in rules.source
