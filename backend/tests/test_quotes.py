from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.core.config import Settings
from app.core.instruments import TRADINGVIEW_PROVIDER
from app.providers.base import ProviderError
from app.services.quotes import (
    QuoteError,
    QuoteService,
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
    "provider": TRADINGVIEW_PROVIDER,
    "provider_symbol": "BINANCE:BTCUSDT",
}

INDIA = {
    "instrument_id": "india:NSE:RELIANCE",
    "symbol": "RELIANCE",
    "name": "RELIANCE",
    "market": "india",
    "exchange": "NSE",
    "currency": "INR",
    "asset_type": "equity",
    "provider": TRADINGVIEW_PROVIDER,
    "provider_symbol": "NSE:RELIANCE",
}


class FakeDb:
    def __init__(self):
        self.snapshots: dict[str, dict] = {}

    def save_quote_snapshot(self, instrument_id, quote):
        self.snapshots[instrument_id] = dict(quote)

    def get_quote_snapshot(self, instrument_id):
        snapshot = self.snapshots.get(instrument_id)
        return dict(snapshot) if snapshot else None


class FakeMarket:
    def __init__(self, quote_map=None, *, error=None, info=None, frame=None):
        self.quote_map = quote_map or {}
        self.error = error
        self.info = info or {}
        self.frame = frame
        self.quote_calls: list[list[str]] = []
        self.candle_calls = 0

    def quotes(self, symbols):
        self.quote_calls.append(list(symbols))
        if self.error:
            raise self.error
        found = {
            symbol: self.quote_map[symbol]
            for symbol in symbols
            if symbol in self.quote_map
        }
        errors = {
            symbol: f"TradingView returned no quote for {symbol}"
            for symbol in symbols
            if symbol not in self.quote_map
        }
        return found, errors

    def symbol_info(self, symbol):
        if isinstance(self.info, Exception):
            raise self.info
        return self.info

    def candles(self, symbol, **kwargs):
        self.candle_calls += 1
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame, TRADINGVIEW_PROVIDER


def build_service(*, market=None, db=None, **overrides):
    settings = Settings(
        _env_file=None,
        quote_crypto_ttl_seconds=10,
        quote_global_ttl_seconds=300,
        quote_india_ttl_seconds=600,
        quote_backoff_base_seconds=5,
        quote_backoff_max_seconds=300,
        **overrides,
    )
    return QuoteService(settings, market or FakeMarket(), db or FakeDb())


def tv_quote(
    price=100.5,
    *,
    delay=0,
    update_mode="streaming",
    time=NOW,
    currency="USDT",
    previous_close=95.0,
):
    return {
        "lp": price,
        "prev_close_price": previous_close,
        "ch": price - previous_close,
        "chp": (price - previous_close) / previous_close * 100,
        "high_price": price + 2,
        "low_price": price - 2,
        "volume": 1234,
        "lp_time": int(time.timestamp()),
        "delay": delay,
        "update_mode": update_mode,
        "currency_code": currency,
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


def test_crypto_quote_success_and_ttl_deduplicates_calls():
    market = FakeMarket({"BINANCE:BTCUSDT": tv_quote()})
    service = build_service(market=market)

    first = service.quote_for(CRYPTO)
    second = service.quote_for(CRYPTO)

    assert first["price"] == 100.5
    assert first["quote_type"] == "real_time"
    assert first["freshness"] == "live"
    assert first["provider"] == TRADINGVIEW_PROVIDER
    assert first["delay_seconds"] == 0
    assert second["price"] == 100.5
    assert len(market.quote_calls) == 1


def test_quotes_for_deduplicates_instrument_identity():
    market = FakeMarket({"BINANCE:BTCUSDT": tv_quote()})
    service = build_service(market=market)
    quotes = service.quotes_for([CRYPTO, dict(CRYPTO), CRYPTO])
    assert len(quotes) == 1
    assert len(market.quote_calls) == 1
    assert market.quote_calls[0] == ["BINANCE:BTCUSDT"]


def test_provider_failure_returns_unavailable_without_losing_cached_snapshot():
    market = FakeMarket(error=ProviderError("bridge offline"))
    service = build_service(market=market)
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


def test_failed_provider_is_not_retried_during_backoff():
    market = FakeMarket(error=ProviderError("bridge offline"))
    service = build_service(market=market)

    first = service.quote_for(CRYPTO)
    second = service.quote_for(CRYPTO)

    assert first["price"] is None
    assert second["price"] is None
    assert len(market.quote_calls) == 1
    assert service._failures[CRYPTO["instrument_id"]].failures == 1


def test_rate_limit_uses_extended_backoff():
    service = build_service(market=FakeMarket(error=ProviderError("rate limit exceeded")))
    quote = service.quote_for(CRYPTO)
    assert quote["price"] is None
    state = service._failures[CRYPTO["instrument_id"]]
    assert state.rate_limited is True
    assert state.message


def test_invalid_crypto_symbol_reports_provider_rejection():
    service = build_service(market=FakeMarket({}))
    quote = service.quote_for(CRYPTO)
    assert quote["price"] is None
    assert "BINANCE:BTCUSDT" in quote["error"]


def test_indian_equity_quote_is_delayed_never_real_time():
    market = FakeMarket({
        "NSE:RELIANCE": tv_quote(
            price=2500.0, delay=900, update_mode="delayed", currency="INR",
            previous_close=2450.0,
        )
    })
    service = build_service(market=market)
    quote = service.quote_for(INDIA)
    assert quote["price"] == 2500.0
    assert quote["quote_type"] == "delayed"
    assert quote["freshness"] == "delayed"
    assert quote["previous_close"] == 2450.0
    assert quote["day_change"] == 50.0
    assert quote["delay_seconds"] == 900
    assert quote["currency"] == "INR"


def test_realtime_quote_within_delay_is_labelled_live():
    service = build_service(
        market=FakeMarket({
            "BINANCE:BTCUSDT": tv_quote(update_mode="streaming", delay=0)
        })
    )
    quote = service.quote_for(CRYPTO)
    assert quote["freshness"] == "live"
    assert quote["quote_type"] == "real_time"


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


def test_newer_quote_is_not_overwritten_by_older_quote():
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
    service._store(CRYPTO, newer)
    service._store(CRYPTO, older)
    assert service._fallback(CRYPTO, "test")["price"] == 101


def test_quotes_for_batches_stale_instruments(monkeypatch):
    market = FakeMarket({
        "NSE:RELIANCE": tv_quote(price=2500.0, currency="INR", delay=900),
    })
    service = build_service(market=market)
    quotes = service.quotes_for([INDIA, CRYPTO])
    assert len(quotes) == 2
    assert quotes[0]["price"] == 2500.0
    assert quotes[1]["price"] is None
    assert market.quote_calls == [["NSE:RELIANCE", "BINANCE:BTCUSDT"]]


def test_market_status_distinguishes_sessions():
    assert market_status_for("crypto", NOW) == "24/7"
    india_open = datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    india_closed = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)  # 19:30 IST
    assert market_status_for("india", india_open) == "open"
    assert market_status_for("india", india_closed) == "closed"


def historical_frame():
    first = (NOW - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    second = first + timedelta(days=1)
    index = pd.DatetimeIndex([first, second], tz="UTC")
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
    return frame, second


def test_historical_transaction_quote_uses_provider_history_not_current_price():
    frame, trade_day = historical_frame()
    service = build_service(market=FakeMarket(frame=frame))
    # 17:30 IST, after the Indian cash close, so the same-day close is final.
    trade_time = trade_day.replace(hour=12)
    quote = service.quote_for_transaction(INDIA, trade_time, now=NOW)
    assert quote["price"] == 200
    assert quote["quote_type"] == "historical"
    assert quote["freshness"] == "historical"
    assert quote["quote_time"] is not None


def test_historical_intraday_equity_does_not_use_same_day_close_before_session_end():
    frame, trade_day = historical_frame()
    service = build_service(market=FakeMarket(frame=frame))
    # 10:30 IST, before the Indian cash close, so the same-day close is not yet
    # knowable. The provider's previous completed close must be used.
    trade_time = trade_day.replace(hour=5)
    quote = service.quote_for_transaction(INDIA, trade_time, now=NOW)
    assert quote["price"] == 100
    assert quote["quote_type"] == "historical"


def test_recent_transaction_quote_uses_live_quote_path():
    service = build_service(market=FakeMarket({
        "NSE:RELIANCE": tv_quote(price=2500.0, currency="INR", delay=900),
    }))
    quote = service.quote_for_transaction(INDIA, NOW - timedelta(minutes=1), now=NOW)
    assert quote["price"] == 2500.0
    assert quote["quote_type"] == "delayed"


def test_trading_rules_use_tradingview_symbol_precision():
    service = build_service(market=FakeMarket(info={
        "pricescale": 100, "minmov": 1, "currency_code": "USDT",
    }))
    rules = service.trading_rules_for(CRYPTO)
    assert rules.quantity_step == 0.0001
    assert rules.is_fallback is False
    assert "TradingView symbol precision" in rules.source


def test_trading_rules_fallback_is_explicit():
    service = build_service(
        market=FakeMarket(info=ProviderError("symbol metadata unavailable"))
    )
    rules = service.trading_rules_for(CRYPTO)
    assert rules.is_fallback is True
    assert "Fallback" in rules.source


def test_historical_quote_error_is_raised_when_no_candle_is_eligible():
    frame = candle_frame()
    service = build_service(market=FakeMarket(frame=frame))
    with pytest.raises(QuoteError, match="Historical price unavailable"):
        service.historical_quote_for(INDIA, NOW - timedelta(days=10), now=NOW)
