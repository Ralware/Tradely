import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.market_data import BinanceSpotProvider, TejHQProvider, YahooFinanceProvider
from app.providers.news import GDELTNewsProvider
from app.services.market import MarketService, _CandleCache


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_tejhq_adjusted_daily_adapter(monkeypatch):
    captured = {}
    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"data": [{
            "date": "2026-11-10", "open": 100, "high": 105, "low": 99,
            "close": 104, "volume": 1000,
        }]})
    monkeypatch.setattr("app.providers.market_data.httpx.get", fake_get)
    settings = Settings(_env_file=None, tejhq_api_key="tej_live_test")
    frame = TejHQProvider(settings).fetch_candles(
        "RELIANCE", market="india", exchange="NSE", interval="1d",
        start=date(2026, 1, 1), end=date(2026, 11, 10),
    )
    assert captured["url"].endswith("/v1/adjusted/nse/RELIANCE")
    assert captured["headers"]["Authorization"] == "Bearer tej_live_test"
    assert frame.iloc[-1]["close"] == 104
    assert frame.attrs["is_adjusted"] is True


def test_tejhq_refuses_intraday_intervals():
    provider = TejHQProvider(Settings(_env_file=None))
    with pytest.raises(ProviderError, match="daily EOD"):
        provider.fetch_candles("RELIANCE", market="india", exchange="NSE", interval="5m",
                               start=None, end=None)


def test_tejhq_uses_keyless_raw_endpoint_without_api_key(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"data": [{
            "date": "2026-11-10", "open": 100, "high": 105, "low": 99,
            "close": 104, "volume": 1000,
        }]})

    monkeypatch.setattr("app.providers.market_data.httpx.get", fake_get)
    frame = TejHQProvider(Settings(_env_file=None)).fetch_candles(
        "RELIANCE", market="india", exchange="NSE", interval="1d", start=None, end=None,
    )
    assert captured["url"].endswith("/v1/ohlcv/nse/RELIANCE")
    assert captured["headers"] == {}
    assert frame.attrs["is_adjusted"] is False


def test_binance_spot_candle_normalization(monkeypatch):
    old = int(pd.Timestamp("2025-01-01T00:00:00Z").timestamp() * 1000)
    payload = [
        [old, "100", "105", "99", "103", "1000", old + 59_999],
        [old + 60_000, "103", "107", "102", "106", "1200", old + 119_999],
    ]
    captured = {}
    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(payload)
    monkeypatch.setattr("app.providers.market_data.httpx.get", fake_get)
    provider = BinanceSpotProvider(Settings(_env_file=None))
    frame = provider.fetch_candles("BTCUSDT", market="crypto", exchange="BINANCE", interval="1m",
                                   start=date(2025, 1, 1), end=date(2025, 1, 2))
    assert captured["url"].endswith("/api/v3/klines")
    assert captured["params"]["symbol"] == "BTCUSDT"
    assert len(frame) == 2
    assert frame.iloc[-1]["close"] == 106


def test_binance_paginates_beyond_1000_candles(monkeypatch):
    first_open = int(pd.Timestamp("2025-01-01T00:00:00Z").timestamp() * 1000)
    minute = 60_000
    first_page = [
        [first_open + i * minute, "100", "101", "99", "100.5", "1000",
         first_open + (i + 1) * minute - 1]
        for i in range(1000)
    ]
    second_open = first_open + 1000 * minute
    second_page = [[second_open, "100.5", "102", "100", "101.5", "1500",
                    second_open + minute - 1]]
    pages = [first_page, second_page]
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs["params"].copy())
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("app.providers.market_data.httpx.get", fake_get)
    frame = BinanceSpotProvider(Settings(_env_file=None)).fetch_candles(
        "BTCUSDT", market="crypto", exchange="BINANCE", interval="1m",
        start=date(2025, 1, 1), end=date(2025, 1, 2),
    )
    assert len(calls) == 2
    assert calls[1]["startTime"] == first_page[-1][6] + 1
    assert len(frame) == 1001
    assert frame.attrs["history_truncated"] is False


def test_binance_history_request_is_bounded_to_2500_candles(monkeypatch):
    first_open = int(pd.Timestamp("2020-01-01T00:00:00Z").timestamp() * 1000)
    minute = 60_000
    calls = []

    def fake_get(url, **kwargs):
        params = kwargs["params"]
        calls.append(params.copy())
        offset = sum(call["limit"] for call in calls[:-1])
        rows = [
            [first_open + (offset + i) * minute, "100", "101", "99", "100.5", "1000",
             first_open + (offset + i + 1) * minute - 1]
            for i in range(params["limit"])
        ]
        return FakeResponse(rows)

    monkeypatch.setattr("app.providers.market_data.httpx.get", fake_get)
    frame = BinanceSpotProvider(Settings(_env_file=None)).fetch_candles(
        "BTCUSDT", market="crypto", exchange="BINANCE", interval="1m",
        start=date(2020, 1, 1), end=None,
    )
    assert [call["limit"] for call in calls] == [1000, 1000, 501]
    assert len(frame) == 2500
    assert frame.attrs["history_truncated"] is True


def test_market_cache_normalizes_identity_and_returns_copies(monkeypatch):
    service = MarketService(Settings(_env_file=None))
    calls = []
    index = pd.to_datetime(["2025-01-02", "2025-01-01", "2025-01-02"], utc=True)
    source_frame = pd.DataFrame({
        "open": [2, 1, 3], "high": [3, 2, 4], "low": [1, 0, 2],
        "close": [2, 1, 3], "volume": [20, 10, 30],
    }, index=index)

    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return source_frame

    monkeypatch.setattr(service.yahoo, "fetch_candles", fetch)
    first, source = service.candles("AAPL", market="global", exchange="NASDAQ")
    first.iloc[0, first.columns.get_loc("close")] = -1
    second, _ = service.candles("aapl", market="global", exchange="nasdaq", provider="yahoo")
    assert len(calls) == 1
    assert source == service.yahoo.name
    assert second.index.is_monotonic_increasing
    assert not second.index.has_duplicates
    assert second.iloc[-1]["close"] == 3
    assert second.iloc[0]["close"] == 1
    assert second.attrs["is_adjusted"] is True


def test_market_cache_deduplicates_concurrent_provider_requests(monkeypatch):
    service = MarketService(Settings(_env_file=None))
    entered = threading.Event()
    release = threading.Event()
    calls = []
    index = pd.date_range("2025-01-01", periods=1, tz="UTC")
    frame = pd.DataFrame({
        "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [10],
    }, index=index)

    def fetch(*args, **kwargs):
        calls.append(1)
        entered.set()
        release.wait(timeout=2)
        return frame

    monkeypatch.setattr(service.yahoo, "fetch_candles", fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.candles, "AAPL", market="global")
        assert entered.wait(timeout=2)
        second = pool.submit(service.candles, "AAPL", market="global")
        time.sleep(0.05)
        release.set()
        assert len(first.result(timeout=2)[0]) == 1
        assert len(second.result(timeout=2)[0]) == 1
    assert len(calls) == 1


def test_market_cache_evicts_entries_at_its_capacity():
    cache = _CandleCache(max_entries=1)
    frame = pd.DataFrame({
        "open": [1], "high": [2], "low": [0.5], "close": [1.5], "volume": [10],
    }, index=pd.date_range("2025-01-01", periods=1, tz="UTC"))
    calls = []

    def load():
        calls.append(1)
        return frame, "source"

    cache.get_or_load(("first",), 60, load)
    cache.get_or_load(("second",), 60, load)
    cache.get_or_load(("first",), 60, load)
    assert len(calls) == 3


def test_yahoo_crypto_symbol_is_normalized_without_double_hyphen(monkeypatch):
    import sys
    from types import SimpleNamespace

    captured = {}
    index = pd.DatetimeIndex([pd.Timestamp("2025-01-01", tz="UTC")])
    download_frame = pd.DataFrame({
        "Open": [100], "High": [105], "Low": [99], "Close": [103], "Volume": [1000],
    }, index=index)

    def fake_download(ticker, **kwargs):
        captured["ticker"] = ticker
        return download_frame

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    from app.providers.market_data import YahooFinanceProvider

    frame = YahooFinanceProvider().fetch_candles(
        "BTCUSDT", market="crypto", exchange=None, interval="1d",
        start=date(2025, 1, 1), end=date(2025, 1, 2),
    )
    assert captured["ticker"] == "BTC-USD"
    assert frame.attrs["is_adjusted"] is True


def test_yahoo_clamps_intraday_history_to_provider_window(monkeypatch):
    import sys
    from types import SimpleNamespace

    captured = {}
    download_frame = pd.DataFrame({
        "Open": [100], "High": [105], "Low": [99], "Close": [103], "Volume": [1000],
    }, index=pd.DatetimeIndex(["2025-04-24T10:00:00Z"]))

    def fake_download(ticker, **kwargs):
        captured.update(kwargs)
        return download_frame

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    frame = YahooFinanceProvider().fetch_candles(
        "AAPL", market="global", exchange="NASDAQ", interval="1m",
        start=date(2025, 1, 1), end=date(2025, 4, 30),
    )
    assert captured["start"] == "2025-04-24"
    assert frame.attrs["history_truncated"] is True


def test_yahoo_rejects_unsupported_intervals():
    with pytest.raises(ProviderError, match="Unsupported Yahoo Finance interval"):
        YahooFinanceProvider().fetch_candles(
            "AAPL", market="global", exchange="NASDAQ", interval="4h",
            start=None, end=None,
        )


def test_gdelt_article_timestamp_normalization(monkeypatch):
    payload = {"articles": [{
        "title": "Example company filing", "url": "https://example.com/story",
        "domain": "example.com", "seendate": "20261111T120000Z",
    }]}
    monkeypatch.setattr("app.providers.news.httpx.get", lambda *a, **k: FakeResponse(payload))
    provider = GDELTNewsProvider(Settings(_env_file=None))
    items = provider.search('"Example Company"', "EXAMPLE")
    assert len(items) == 1
    assert items[0].published_at == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert items[0].url == "https://example.com/story"


def test_market_routing_does_not_cross_market_providers(monkeypatch):
    service = MarketService(Settings(_env_file=None))
    calls: list[str] = []

    def reject(name):
        def fetch(*args, **kwargs):
            calls.append(name)
            raise ProviderError(name)
        return fetch

    monkeypatch.setattr(service.tejhq, "fetch_candles", reject("tejhq"))
    monkeypatch.setattr(service.yahoo, "fetch_candles", reject("yahoo"))
    monkeypatch.setattr(service.binance, "fetch_candles", reject("binance"))

    with pytest.raises(ProviderError):
        service.candles("RELIANCE", market="india")
    assert calls == ["tejhq"]
    calls.clear()
    with pytest.raises(ProviderError):
        service.candles("BTCUSDT", market="crypto")
    assert calls == ["binance"]
    calls.clear()
    with pytest.raises(ProviderError):
        service.candles("AAPL", market="global")
    assert calls == ["yahoo"]


def test_market_service_rejects_incompatible_manual_provider():
    service = MarketService(Settings(_env_file=None))
    with pytest.raises(ValueError, match="not compatible"):
        service.candles("RELIANCE", market="india", provider="yahoo")
