from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_private_no_ai_no_paper_trading():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "private-single-user"
    assert response.json()["ai"] is False
    assert response.json()["paper_trading"] is False
    assert response.json()["order_execution"] is False


def test_root_serves_react_production_build():
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="root"' in response.text


def test_risk_endpoint_returns_expected_sizing():
    response = client.post("/api/risk/position-size", json={
        "capital": 100000, "risk_fraction": 0.005, "entry": 1000, "stop": 980
    })
    assert response.status_code == 200
    assert response.json()["quantity"] == 25
    assert response.json()["planned_loss"] == 500

def test_risk_endpoint_accepts_short_direction_and_requires_a_higher_stop():
    response = client.post("/api/risk/position-size", json={
        "capital": 100000,
        "risk_fraction": 0.005,
        "entry": 100,
        "stop": 110,
        "direction": "SHORT",
    })
    assert response.status_code == 200
    assert response.json()["direction"] == "SHORT"
    assert response.json()["risk_per_unit"] == 10
    invalid = client.post("/api/risk/position-size", json={
        "capital": 100000,
        "risk_fraction": 0.005,
        "entry": 100,
        "stop": 90,
        "direction": "SHORT",
    })
    assert invalid.status_code == 422


def test_daily_backtest_rejects_intraday_interval():
    response = client.post("/api/backtests/trend-breakout", json={
        "symbol": "RELIANCE", "market": "india", "interval": "15m"
    })
    assert response.status_code == 422


def test_removed_endpoints_return_not_found():
    assert client.get("/api/crypto/markets").status_code == 404
    assert client.get("/api/instruments/AAPL/fundamentals?market=global").status_code == 404
    assert client.get("/api/instruments/AAPL/events?market=global").status_code == 404
    assert client.get("/api/us/issuers/0000320193/filings").status_code == 404


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


def test_news_returns_an_explicit_empty_result():
    response = client.get("/api/instruments/AAPL/news?market=global")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "AAPL"
    assert body["market"] == "global"
    assert body["items"] == []
    assert body["count"] == 0
    assert body["providers"] == {}
    assert "not configured" in body["note"]


def test_news_accepts_an_instrument_id():
    response = client.get(
        "/api/instruments/RELIANCE/news",
        params={"instrument_id": "india:NSE:RELIANCE"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["instrument"]["instrument_id"] == "india:NSE:RELIANCE"
    assert body["count"] == 0


def test_catalogue_refresh_without_query_explains_live_search():
    response = client.post("/api/instruments/catalogue/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 0
    source = body["sources"]["TradingView market search"]
    assert source["entries"] == 0
    assert "q=" in source["note"]


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


def test_intraday_analysis_evaluates_signals_instead_of_returning_insufficient_data(monkeypatch):
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
    assert body["strategy"]["state"] != "INSUFFICIENT_DATA"
    assert body["strategy"]["conditions"]


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
    monkeypatch.setattr(
        app.state.db,
        "save_signal",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("technicals must be read-only")),
    )

    response = client.get("/api/instruments/TEST/technicals?market=india&interval=1d")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "TEST"
    assert body["source"] == "test"
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
