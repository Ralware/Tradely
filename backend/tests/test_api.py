from app.main import app
from app.core.models import WatchlistItem
from fastapi.testclient import TestClient
import numpy as np
import pandas as pd

client = TestClient(app, base_url="http://127.0.0.1")


def test_health_reports_private_no_ai_no_paper_trading():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "private-single-user"
    assert response.json()["ai"] is False
    assert response.json()["paper_trading"] is False
    assert response.json()["order_execution"] is False


def test_precomputed_get_is_persistence_only(monkeypatch):
    identity = "global:NASDAQ:MSFT"
    expected = {"interval": "1d", "fingerprint": "stored", "analysis": {"candles": []}}
    monkeypatch.setattr(app.state.analytics_precompute, "get_snapshot", lambda instrument_id, interval: expected)

    def forbidden(*args, **kwargs):
        raise AssertionError("Prepared GET must not retrieve or calculate Analytics")

    monkeypatch.setattr(app.state.market_service, "candles", forbidden)
    response = client.get(f"/api/analytics/precomputed/{identity}/1d")
    assert response.status_code == 200
    assert response.json() == expected


def test_on_demand_analytics_uses_canonical_identity_and_returns_persisted_bundle(monkeypatch):
    identity = "global:NASDAQ:MSFT"
    expected = {"interval": "1d", "fingerprint": "stable", "provenance": {"instrument_id": identity}}
    monkeypatch.setattr(app.state.instrument_resolver, "get", lambda instrument_id: {
        "instrument_id": identity, "symbol": "MSFT", "market": "global",
    } if instrument_id == identity else None)
    calls = []
    monkeypatch.setattr(app.state.analytics_precompute, "get_or_compute_snapshot",
                        lambda instrument_id, interval, refresh_latest: calls.append((instrument_id, interval, refresh_latest)) or expected)

    response = client.get(f"/api/analytics/on-demand/{identity}/1d")

    assert response.status_code == 200
    assert response.json() == expected
    assert calls == [(identity, "1d", False)]


def test_non_watchlisted_search_miss_fetches_persists_and_reuses_complete_analytics(monkeypatch):
    import numpy as np
    import pandas as pd

    identity = "global:NASDAQ:MSFT"
    instrument = app.state.db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    frame_index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=260, freq="D")
    close = pd.Series(100 + np.arange(260) * 0.2 + np.sin(np.arange(260) / 5), index=frame_index)
    frame = pd.DataFrame({"open": close - .1, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1000 + np.arange(260)}, index=frame_index)
    frame.attrs.update({"is_adjusted": True, "last_bar_confirmed": True})
    calls = []
    monkeypatch.setattr(app.state.instrument_resolver, "get", lambda _id: app.state.db.instrument_for_id(identity))
    monkeypatch.setattr(app.state.market_service, "candles",
                        lambda *args, **kwargs: calls.append(kwargs) or (frame.copy(), "mock-live"))

    first = client.get(f"/api/analytics/on-demand/{instrument.instrument_id}/1d")
    second = client.get(f"/api/analytics/on-demand/{instrument.instrument_id}/1d")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.headers["content-encoding"] == "gzip"
    assert int(first.headers["content-length"]) < len(first.content)
    assert len(first.json()["analysis"]["candles"]) == 260
    assert first.json()["technical_ratings"]["fingerprint"] == first.json()["fingerprint"]
    assert first.json()["fingerprint"] == second.json()["fingerprint"]
    assert len(calls) == 1
    assert all(item.get("instrument_id") != identity for item in app.state.db.get_watchlist())
    assert app.state.analytics_precompute.get_snapshot(identity, "1d") is not None


def test_watchlist_add_confirms_prefetch_registration_after_persisting(monkeypatch):
    identity = "global:NASDAQ:MSFT"
    registration = {"instrument_id": identity, "registered": True, "reused": 1, "queued": 2}
    monkeypatch.setattr(app.state.analytics_precompute, "register_watchlist_instrument",
                        lambda instrument_id: registration)
    response = client.post("/api/watchlist", json={"instrument_id": identity})

    assert response.status_code == 200
    body = response.json()
    assert body["instrument_id"] == identity
    assert body["prefetch_registration"] == registration
    assert any(item["instrument_id"] == identity for item in app.state.db.get_watchlist())
    removed = client.delete(f"/api/watchlist/instruments/{identity}")
    assert removed.status_code == 200


def test_watchlist_membership_survives_prefetch_registration_failure_and_can_be_retried(monkeypatch):
    identity = "global:NASDAQ:AAPL"
    monkeypatch.setattr(
        app.state.analytics_precompute,
        "register_watchlist_instrument",
        lambda instrument_id: (_ for _ in ()).throw(RuntimeError("temporary queue failure")),
    )
    failed = client.post("/api/watchlist", json={"instrument_id": identity})
    assert failed.status_code == 503
    assert failed.json()["detail"]["watchlist_saved"] is True
    assert any(item["instrument_id"] == identity for item in app.state.db.get_watchlist())

    monkeypatch.setattr(app.state.analytics_precompute, "register_watchlist_instrument", lambda _id: {
        "instrument_id": identity, "registered": True, "reused": 0, "queued": 3,
    })
    retried = client.post("/api/watchlist", json={"instrument_id": identity})
    assert retried.status_code == 200
    assert retried.json()["prefetch_registration"]["registered"] is True
    assert client.delete(f"/api/watchlist/instruments/{identity}").json()["removed"] is True


def test_root_serves_react_production_build():
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_client_side_routes_serve_the_spa_and_unknown_api_paths_stay_404():
    for route in ("/analysis", "/portfolio", "/backtesting"):
        response = client.get(route)
        assert response.status_code == 200
        assert 'id="root"' in response.text
    assert client.get("/api/unknown-route").status_code == 404


def test_backtest_validates_risk_budget_before_fetching_data():
    for risk in (-0.01, 0, 0.03):
        response = client.post("/api/backtests/trend-breakout", json={
            "symbol": "MSFT", "market": "global", "risk_fraction": risk,
        })
        assert response.status_code == 422


def test_daily_backtest_rejects_intraday_interval():
    response = client.post("/api/backtests/trend-breakout", json={
        "symbol": "RELIANCE", "market": "india", "interval": "15m"
    })
    assert response.status_code == 422


def test_market_candles_route_passes_bounded_days_to_provider(monkeypatch):
    instrument = app.state.db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=2, freq="D")
    frame = pd.DataFrame({"open": [1., 2.], "high": [2., 3.], "low": [.5, 1.5],
                          "close": [1.5, 2.5], "volume": [10., 20.]}, index=index)
    forming = {"timestamp": index[-1].isoformat(), "open": 2.5, "high": 3.,
               "low": 2., "close": 2.75, "volume": 7.}
    frame.attrs["forming_candle"] = forming
    received = {}
    monkeypatch.setattr(app.state.market_service, "candles",
                        lambda *args, **kwargs: received.update(kwargs) or (frame, "test-provider"))
    monkeypatch.setattr(app.state.market_service, "price_metadata", lambda *args, **kwargs: {})

    response = client.get("/api/market/candles", params={
        "instrument_id": instrument.instrument_id, "days": 7, "refresh_latest": True,
    })

    assert response.status_code == 200
    assert received["days"] == 7
    assert received["full_history"] is False
    assert received["refresh_latest"] is True
    assert response.json()["forming_candle"] == forming


def test_batched_sparkline_route_bounds_and_reuses_market_candles(monkeypatch):
    instrument = app.state.db.resolve_instrument("MSFT", "global", exchange="NASDAQ")
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=3, freq="h")
    frame = pd.DataFrame({
        "open": [1., 2., 3.], "high": [2., 3., 4.], "low": [.5, 1.5, 2.5],
        "close": [1.5, 2.5, 3.5], "volume": [10., 20., 30.],
    }, index=index)
    calls = []
    monkeypatch.setattr(
        app.state.market_service,
        "candles",
        lambda *args, **kwargs: calls.append(kwargs) or (frame, "test-provider"),
    )

    response = client.post("/api/sparklines", json={
        "instrument_ids": [instrument.instrument_id],
        "interval": "1h",
        "days": 1,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][instrument.instrument_id]["closes"] == [1.5, 2.5, 3.5]
    assert calls[0]["full_history"] is False
    assert calls[0]["days"] == 1


def test_unknown_indian_adjustment_suppresses_analysis_and_refuses_backtest(monkeypatch):
    instrument = app.state.db.resolve_instrument("RELIANCE", "india", exchange="NSE")
    index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("D"), periods=260, freq="D")
    close = pd.Series(100 + np.arange(260) * .2 + np.sin(np.arange(260) / 5), index=index)
    frame = pd.DataFrame({"open": close - .1, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1000 + np.arange(260)}, index=index)
    frame.attrs.update({"adjustment_status": "unknown", "is_adjusted": True})
    monkeypatch.setattr(app.state.market_service, "candles", lambda *args, **kwargs: (frame.copy(), "mock"))

    analysis = client.get(f"/api/instruments/{instrument.symbol}/analysis", params={"instrument_id": instrument.instrument_id})
    assert analysis.status_code == 200
    body = analysis.json()
    assert body["adjustment_status"] == "unknown"
    assert body["is_adjusted"] is None
    assert any("could not be verified" in warning for warning in body["warnings"])

    backtest = client.post("/api/backtests/trend-breakout", json={
        "instrument_id": instrument.instrument_id, "interval": "1d", "days": 365,
    })
    assert backtest.status_code == 409
    assert "could not be verified" in backtest.json()["detail"]


def test_removed_endpoints_return_not_found():
    assert client.get("/api/scanner/watchlist").status_code == 404
    assert client.post("/api/risk/position-size", json={}).status_code == 404
    assert client.get("/api/crypto/markets").status_code == 404
    assert client.get("/api/instruments/AAPL/fundamentals?market=global").status_code == 404
    assert client.get("/api/instruments/AAPL/events?market=global").status_code == 404
    assert client.get("/api/us/issuers/0000320193/filings").status_code == 404
    assert client.get("/api/signals/history").status_code == 404
    assert client.get("/api/watchlist/quotes").status_code == 404
    assert client.get("/api/instruments/india:NSE:RELIANCE/quote").status_code == 404
    assert client.get("/api/instruments/india:NSE:RELIANCE/history").status_code == 404
    assert client.get("/api/instruments/india:NSE:RELIANCE/capabilities").status_code == 404
    assert client.post("/api/instruments/catalogue/refresh").status_code == 404


def test_provider_status_reports_only_tradingview_and_bridge():
    response = client.get("/api/providers/status")
    assert response.status_code == 200
    body = response.json()
    providers = body["providers"]
    assert [provider["name"] for provider in providers] == ["TradingView (unofficial)"]
    assert providers[0]["configured"] is True
    assert "TradingView bridge" in providers[0]["note"] or "bridge" in providers[0]["note"]
    assert "bridge" in body
    assert "checked_at" in body


def test_legacy_news_route_returns_explicit_yahoo_only_empty_result(monkeypatch):
    monkeypatch.setattr(app.state.news_service, "request_refresh", lambda *args, **kwargs: False)
    response = client.get("/api/instruments/AAPL/news?market=global")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["market"] == "global"
    assert body["items"] == []
    assert body["count"] == 0
    assert body["providers"] == {"Yahoo Finance": "unknown"}
    assert "only from Yahoo Finance" in body["note"]


def test_news_accepts_an_instrument_id(monkeypatch):
    monkeypatch.setattr(app.state.news_service, "request_refresh", lambda *args, **kwargs: False)
    response = client.get(
        "/api/instruments/RELIANCE/news",
        params={"instrument_id": "india:NSE:RELIANCE"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["instrument"]["instrument_id"] == "india:NSE:RELIANCE"
    assert body["count"] == 0


def test_news_api_feed_filters_and_status_use_canonical_instrument(monkeypatch):
    monkeypatch.setattr(app.state.news_service, "request_refresh", lambda *args, **kwargs: False)
    feed = client.get("/api/news/AAPL", params={
        "instrument_id": "global:NASDAQ:AAPL", "q": "earnings",
        "date_from": "2024-01-01", "date_to": "2024-01-31", "page_size": 5,
    })
    assert feed.status_code == 200
    assert feed.json()["symbol"] == "AAPL"
    assert feed.json()["items"] == []
    assert feed.json()["page_size"] == 5
    status = client.get("/api/news/status", params={"instrument_id": "global:NASDAQ:AAPL"})
    assert status.status_code == 200
    assert status.json()["provider"] == "Yahoo Finance"


def test_general_news_api_normalizes_timezone_aware_date_bounds(monkeypatch):
    received = {}

    def capture_feed(**kwargs):
        received.update(kwargs)
        return {"items": [], "count": 0, "page": 1, "page_size": 20}

    monkeypatch.setattr(app.state.news_service, "general_feed", capture_feed)
    response = client.get("/api/news", params={
        "date_from": "2026-10-23T00:00:00+05:30",
        "date_to": "2026-11-23T23:59:59.999999+05:30",
    })

    assert response.status_code == 200
    assert received["date_from"] == "2026-10-22T18:30:00+00:00"
    assert received["date_to"] == "2026-11-23T18:29:59.999999+00:00"
    invalid = client.get("/api/news", params={"date_from": "not-a-date"})
    assert invalid.status_code == 422


def test_news_instrument_search_and_manual_refresh_are_yahoo_service_backed(monkeypatch):
    monkeypatch.setattr(app.state.news_service, "search_instruments", lambda query: {
        "query": query,
        "items": [{"instrument_id": "global:NASDAQ:AAPL", "symbol": "AAPL", "name": "Apple Inc."}],
        "count": 1,
        "provider": "Yahoo Finance",
    })
    search = client.get("/api/news/search", params={"q": "Apple"})
    assert search.status_code == 200
    assert search.json()["items"][0]["symbol"] == "AAPL"
    monkeypatch.setattr(app.state.news_service, "request_refresh", lambda *args, **kwargs: True)
    refresh = client.post("/api/news/AAPL/refresh", params={"instrument_id": "global:NASDAQ:AAPL"})
    assert refresh.status_code == 200
    assert refresh.json()["status"] == "queued"


def test_indicator_series_is_additive_and_uses_backend_calculations(monkeypatch):
    import numpy as np
    import pandas as pd
    from app.main import app

    index = pd.date_range("2025-01-01", periods=260, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100.0, 200.0, 260), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1000.0},
        index=index,
    )
    frame.attrs["is_adjusted"] = True

    monkeypatch.setattr(app.state.market_service, "candles", lambda *args, **kwargs: (frame, "test"))

    response = client.get("/api/instruments/TEST/indicators?market=india&limit=120")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 120
    assert body["source"] == "test"
    assert body["is_adjusted"] is True
    assert body["series"][-1]["close"] == 200.0
    assert "sma_200" in body["series"][-1]
    assert "rsi_14" in body["series"][-1]


def test_intraday_analysis_returns_indicators_for_requested_interval(monkeypatch):
    import numpy as np
    import pandas as pd
    from app.main import app

    end = pd.Timestamp.now(tz="UTC").floor("4h")
    index = pd.date_range(end=end, periods=320, freq="4h")
    close = pd.Series(np.linspace(100.0, 200.0, 320), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1000.0},
        index=index,
    )
    frame.attrs["is_adjusted"] = True

    monkeypatch.setattr(app.state.market_service, "candles", lambda *args, **kwargs: (frame, "test"))

    response = client.get(
        "/api/instruments/BTCUSDT/analysis?market=crypto&exchange=BINANCE&interval=4h"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interval"] == "4h"
    assert len(body["candles"]) == 320
    assert body["indicators"]["sma_200"] is not None
    assert body["latest"]["close"] == frame.iloc[-1]["close"]


def test_completed_weekly_and_monthly_bars_use_interval_aware_freshness():
    from datetime import timedelta

    import pandas as pd
    from app.api.routes import _is_stale

    now = pd.Timestamp.now(tz="UTC")
    weekly = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([now - timedelta(days=7)]))
    monthly = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([now - timedelta(days=45)]))
    old_weekly = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([now - timedelta(days=15)]))
    old_monthly = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([now - timedelta(days=63)]))

    assert _is_stale(weekly, "crypto", "1wk") is False
    assert _is_stale(monthly, "crypto", "1mo") is False
    assert _is_stale(old_weekly, "crypto", "1wk") is True
    assert _is_stale(old_monthly, "crypto", "1mo") is True


def test_technicals_endpoint_classifies_existing_values_without_writing_signals(monkeypatch):
    import numpy as np
    import pandas as pd
    from app.main import app

    index = pd.date_range("2024-01-01", periods=320, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100.0, 220.0, 320), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1000.0},
        index=index,
    )
    frame.attrs["is_adjusted"] = True

    monkeypatch.setattr(app.state.market_service, "candles", lambda *args, **kwargs: (frame, "test"))
    prior_transactions = app.state.db.list_transactions()

    response = client.get("/api/instruments/TEST/technicals?market=india&interval=1d")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "TEST"
    assert body["source"] == "test"
    assert app.state.db.list_transactions() == prior_transactions
    assert body["close"] == 220.0
    assert "strategy" not in body
    assert "method" in body

    allowed = {"Buy", "Sell", "Neutral"}
    rows = body["oscillators"] + body["moving_averages"]
    assert len(body["moving_averages"]) == 7
    assert len(body["oscillators"]) >= 8
    assert {row["action"] for row in rows} <= allowed
    assert all(row["value"] is not None for row in body["moving_averages"])
    assert all(row["action"] == "Buy" for row in body["moving_averages"])

    for key in ("oscillators", "moving_averages", "overall"):
        summary = body["summary"][key]
        assert summary["sell"] + summary["neutral"] + summary["buy"] > 0
        assert -1.0 <= summary["score"] <= 1.0
    assert body["summary"]["moving_averages"]["buy"] == 7
    assert body["summary"]["moving_averages"]["sell"] == 0
