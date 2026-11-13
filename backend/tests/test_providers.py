from datetime import date, datetime, timezone

import pandas as pd
import pytest

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.crypto_metadata import CoinGeckoProvider
from app.providers.market_data import BinanceSpotProvider, TejHQProvider
from app.providers.news import GDELTNewsProvider, SECEdgarProvider, TejHQActionsProvider


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


def test_gdelt_article_timestamp_normalization(monkeypatch):
    payload = {"articles": [{
        "title": "Example company filing", "url": "https://example.com/story",
        "domain": "example.com", "seendate": "20261111T120000Z",
    }]}
    monkeypatch.setattr("app.providers.news.httpx.get", lambda *a, **k: FakeResponse(payload))
    provider = GDELTNewsProvider(Settings(_env_file=None))
    items = provider.search('"Example Company"', "EXAMPLE")
    assert len(items) == 1
    assert items[0].published_at == datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
    assert items[0].url == "https://example.com/story"


def test_tejhq_actions_are_stock_specific(monkeypatch):
    payload = {"data": [{
        "exchange": "NSE", "symbol": "RELIANCE", "ex_date": "2026-12-01",
        "type": "Dividend", "raw_subject": "Dividend recommendation",
    }]}
    monkeypatch.setattr("app.providers.news.httpx.get", lambda *a, **k: FakeResponse(payload))
    provider = TejHQActionsProvider(Settings(_env_file=None))
    items = provider.get_actions("RELIANCE")
    assert len(items) == 1
    assert items[0].symbol == "RELIANCE"
    assert items[0].event_date.isoformat() == "2026-12-01"
    assert items[0].status == "confirmed"


def test_coingecko_requires_demo_key():
    provider = CoinGeckoProvider(Settings(_env_file=None, coingecko_api_key=""))
    with pytest.raises(ProviderError, match="API key is not configured"):
        provider.markets(["btc"])


def test_sec_requires_real_user_agent():
    provider = SECEdgarProvider(Settings(_env_file=None))
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        provider.recent_filings("0000320193")


def test_yahoo_fundamentals_adapter_is_best_effort(monkeypatch):
    import sys
    from types import SimpleNamespace

    from app.providers.fundamentals import YahooFundamentalsProvider

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.quarterly_income_stmt = pd.DataFrame({pd.Timestamp("2026-09-30"): [10]}, index=["Total Revenue"])
            self.quarterly_balance_sheet = pd.DataFrame()
            self.quarterly_cashflow = pd.DataFrame()

        def get_info(self):
            return {"symbol": self.symbol, "marketCap": 1000000, "trailingPE": 20.5}

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))
    result = YahooFundamentalsProvider().fetch("RELIANCE", "india", "NSE")
    assert result["symbol"] == "RELIANCE.NS"
    assert result["profile"]["marketCap"] == 1000000
    assert result["quarterly_income_statement"]["rows"][0]["metric"] == "Total Revenue"
