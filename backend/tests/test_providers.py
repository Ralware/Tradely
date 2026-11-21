import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from app.core.config import Settings
from app.core.instruments import TRADINGVIEW_PROVIDER
from app.providers.base import ProviderError, normalize_candles
from app.providers.tradingview import TradingViewProvider
from app.services.market import MarketService, _CandleCache


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def candle_row(timestamp, close=104.0, volume=1000):
    return {
        "time": int(pd.Timestamp(timestamp).timestamp()),
        "open": close - 4,
        "high": close + 1,
        "low": close - 5,
        "close": close,
        "volume": volume,
    }


def test_tradingview_candle_adapter_uses_exchange_symbol_and_split_adjustment(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse({"candles": [candle_row("2026-11-10T00:00:00Z")]})

    monkeypatch.setattr("app.providers.tradingview.httpx.get", fake_get)
    provider = TradingViewProvider(Settings(_env_file=None))
    frame = provider.fetch_candles(
        "RELIANCE", market="india", exchange="NSE", interval="1d",
        start=date(2026, 1, 1), end=date(2026, 11, 10),
    )

    assert captured["url"].endswith("/candles")
    assert captured["params"]["symbol"] == "NSE:RELIANCE"
    assert captured["params"]["timeframe"] == "D"
    assert captured["params"]["adjustment"] == "splits"
    assert captured["params"]["from"] == int(pd.Timestamp("2026-01-01", tz="UTC").timestamp())
    assert captured["params"]["to"] == int(pd.Timestamp("2026-11-11", tz="UTC").timestamp()) - 1
    assert "count" not in captured["params"]
    assert frame.iloc[-1]["close"] == 104.0
    assert frame.attrs["is_adjusted"] is True
    assert frame.attrs["provider_symbol"] == "NSE:RELIANCE"
    assert frame.attrs["source"] == TRADINGVIEW_PROVIDER


def test_tradingview_candle_adapter_requests_maximum_history_when_no_range(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["params"] = params
        return FakeResponse({"candles": [candle_row("2026-11-10T00:00:00Z")]})

    monkeypatch.setattr("app.providers.tradingview.httpx.get", fake_get)
    frame = TradingViewProvider(Settings(_env_file=None)).fetch_candles(
        "AAPL", market="global", exchange="NASDAQ", interval="1d",
        start=None, end=None,
    )

    assert captured["params"]["count"] == 1_000_000
    assert "from" not in captured["params"]
    assert "to" not in captured["params"]
    assert len(frame) == 1


def test_tradingview_rejects_unsupported_interval():
    provider = TradingViewProvider(Settings(_env_file=None))
    with pytest.raises(ProviderError, match="Unsupported TradingView interval"):
        provider.fetch_candles(
            "AAPL", market="global", exchange="NASDAQ", interval="2d",
            start=None, end=None,
        )


def test_tradingview_requires_an_exchange():
    provider = TradingViewProvider(Settings(_env_file=None))
    with pytest.raises(ProviderError, match="exchange-qualified"):
        provider.fetch_candles(
            "AAPL", market="global", exchange=None, interval="1d",
            start=None, end=None,
        )


def test_normalize_candles_keeps_the_full_requested_range():
    index = pd.date_range("2026-01-01", periods=2600, freq="min", tz="UTC")
    frame = pd.DataFrame({
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0,
    }, index=index)
    normalized = normalize_candles(frame)
    assert len(normalized) == len(frame)
    assert normalized.index[0] == frame.index[0]
    assert normalized.index[-1] == frame.index[-1]


def test_tradingview_drops_the_still_forming_final_candle(monkeypatch):
    now = pd.Timestamp.now(tz="UTC").floor("min")
    rows = [
        candle_row(now - pd.Timedelta(minutes=2), close=100.0),
        candle_row(now - pd.Timedelta(minutes=1), close=101.0),
        candle_row(now, close=999.0),
    ]
    monkeypatch.setattr(
        "app.providers.tradingview.httpx.get",
        lambda *a, **k: FakeResponse({"candles": rows}),
    )
    today = datetime.now(UTC).date()
    frame = TradingViewProvider(Settings(_env_file=None)).fetch_candles(
        "BTCUSDT", market="crypto", exchange="BINANCE", interval="1m",
        start=today, end=today,
    )
    assert len(frame) == 2
    assert frame.iloc[-1]["close"] == 101.0


def test_tradingview_bridge_http_error_is_actionable(monkeypatch):
    monkeypatch.setattr(
        "app.providers.tradingview.httpx.get",
        lambda *a, **k: FakeResponse({"error": {"message": "symbol not found"}}, status_code=404),
    )
    with pytest.raises(ProviderError, match="HTTP 404: symbol not found"):
        TradingViewProvider(Settings(_env_file=None)).symbol_info("NASDAQ:MISSING")


def test_tradingview_symbol_metadata_and_search(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/symbol"):
            assert params == {"symbol": "NSE:RELIANCE"}
            return FakeResponse({"info": {"pricescale": 100, "minmov": 1, "currency_code": "INR"}})
        if url.endswith("/search"):
            assert params == {"q": "RELIANCE", "limit": 5}
            return FakeResponse({"results": [{"symbol": "RELIANCE", "exchange": "NSE"}]})
        raise AssertionError(url)

    monkeypatch.setattr("app.providers.tradingview.httpx.get", fake_get)
    provider = TradingViewProvider(Settings(_env_file=None))
    info = provider.symbol_info("NSE:RELIANCE")
    results = provider.search("RELIANCE", limit=5)
    assert info["pricescale"] == 100
    assert results[0]["exchange"] == "NSE"


def test_market_cache_normalizes_identity_and_returns_copies(monkeypatch):
    service = MarketService(Settings(_env_file=None))
    calls = []
    index = pd.to_datetime(["2025-01-02", "2025-01-01", "2025-01-02"], utc=True)
    source_frame = pd.DataFrame({
        "open": [2, 1, 3], "high": [3, 2, 4], "low": [1, 0, 2],
        "close": [2, 1, 3], "volume": [20, 10, 30],
    }, index=index)
    source_frame.attrs["is_adjusted"] = True

    def fetch(*args, **kwargs):
        calls.append(kwargs)
        return source_frame

    monkeypatch.setattr(service.tradingview, "fetch_candles", fetch)
    first, source = service.candles("AAPL", market="global", exchange="NASDAQ")
    first.iloc[0, first.columns.get_loc("close")] = -1
    second, _ = service.candles(
        "aapl", market="global", exchange="nasdaq", provider="tradingview"
    )
    assert len(calls) == 1
    assert source == TRADINGVIEW_PROVIDER
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

    monkeypatch.setattr(service.tradingview, "fetch_candles", fetch)
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


def test_market_service_rejects_removed_provider_names():
    service = MarketService(Settings(_env_file=None))
    with pytest.raises(ValueError, match="auto or tradingview"):
        service.candles("RELIANCE", market="india", provider="yahoo")


def test_market_service_quotes_and_health_pass_through(monkeypatch):
    service = MarketService(Settings(_env_file=None))
    monkeypatch.setattr(
        service.tradingview,
        "quotes",
        lambda symbols: ({"NSE:RELIANCE": {"lp": 2500}}, {"NSE:BAD": "missing"}),
    )
    monkeypatch.setattr(service.tradingview.bridge, "health", lambda: {"status": "ok"})
    quotes, errors = service.quotes(["NSE:RELIANCE", "NSE:BAD"])
    assert quotes["NSE:RELIANCE"]["lp"] == 2500
    assert errors["NSE:BAD"] == "missing"
    assert service.bridge_health()["status"] == "ok"

@pytest.mark.parametrize("interval,start,before,after", [
    ("1wk", "2024-01-01", "2024-01-07T23:59Z", "2024-01-08T00:00Z"),
    ("1mo", "2024-01-01", "2024-01-31T23:59Z", "2024-02-01T00:00Z"),
])
def test_crypto_finality_uses_continuous_utc_sessions(interval, start, before, after):
    from app.providers.tradingview import _drop_incomplete_final_bar

    frame = pd.DataFrame({"close": [100.]}, index=[pd.Timestamp(start, tz="UTC")])
    assert _drop_incomplete_final_bar(frame, interval, "crypto", now=pd.Timestamp(before)).empty
    assert len(_drop_incomplete_final_bar(frame, interval, "crypto", now=pd.Timestamp(after))) == 1
